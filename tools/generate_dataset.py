#!/usr/bin/env python3
"""
Generate the Marley Health demo dataset (synthetic) as dependency-ordered CSV files.

Target: Frappe v16 + ERPNext v16 + Marley Health (healthcare) v16.6.1
All people, phone numbers, IDs and e-mails are fictitious. E-mails use example.com.

Usage:
    python3 generate_dataset.py --out ../marley_demo_data/data \
        --company "Marley Health Demo" --abbr MHD --anchor 2026-10-13

The CSV headers use Frappe fieldnames (child tables as <table_field>.<fieldname>),
which the v16 Data Import tool matches directly. Columns starting with "_" are
loader-only references; Data Import skips them with a warning.
"""

import argparse
import csv
import datetime as dt
import json
import os
import random

SEED = 16061  # Marley 16.6.1 -> reproducible output

# --------------------------------------------------------------------------------------
# Static master data
# --------------------------------------------------------------------------------------

UOMS = [("mg", 0), ("mcg", 0), ("mL", 0), ("g", 0)]

LAB_TEST_UOMS = ["g/dL", "x10^9/L", "x10^12/L", "fL", "uIU/mL", "mmol/L"]

NEW_DEPARTMENTS = ["General Medicine", "Family Medicine", "Paediatrics"]

# Healthcare Services item group for consultations, procedures, beds
SERVICE_ITEMS = [
    # item_code, item_name, rate (OMR), description
    ("MHD-CONS-GP", "OPD Consultation - General", 12.000, "Outpatient consultation, general / family medicine"),
    ("MHD-CONS-SPEC", "OPD Consultation - Specialist", 20.000, "Outpatient consultation, specialist"),
    ("MHD-CONS-FU", "OPD Follow-up Visit", 8.000, "Outpatient follow-up visit within validity"),
    ("MHD-IP-VISIT", "Inpatient Visit Charge", 15.000, "Daily inpatient practitioner visit"),
]

APPOINTMENT_TYPES = [
    # name, duration, colour
    ("Consultation", 15, "#3b82f6"),
    ("Follow-up", 15, "#10b981"),
    ("Procedure Visit", 30, "#f59e0b"),
    ("Annual Health Check", 30, "#8b5cf6"),
]

SERVICE_UNIT_TYPES = [
    # service_unit_type, allow_appointments, inpatient_occupancy, is_billable, item_code, rate, uom, no_of_hours
    ("Consultation Room", 1, 0, 0, "", "", "", ""),
    ("Procedure Room", 1, 0, 0, "", "", "", ""),
    ("Laboratory", 1, 0, 0, "", "", "", ""),
    ("General Ward Bed", 0, 1, 1, "MHD-WARD-BED", 35.000, "Day", 24),
]

PRACTITIONERS = [
    # first, last, gender, department, schedule, room, charge item, charge, mobile
    ("Salim", "Al Harthy", "Male", "General Medicine", "Marley Morning Sun-Thu", "OPD Room 1", "MHD-CONS-GP", 12.000),
    ("Maryam", "Al Lawati", "Female", "Family Medicine", "Marley Evening Sun-Thu", "OPD Room 2", "MHD-CONS-GP", 12.000),
    ("Rajesh", "Menon", "Male", "Cardiology", "Marley Morning Sun-Thu", "OPD Room 3", "MHD-CONS-SPEC", 20.000),
    ("Fatma", "Al Rawahi", "Female", "Diabetology", "Marley Morning Sun-Thu", "OPD Room 4", "MHD-CONS-SPEC", 20.000),
    ("Ahmed", "Al Busaidi", "Male", "Paediatrics", "Marley Evening Sun-Thu", "OPD Room 5", "MHD-CONS-SPEC", 18.000),
    ("Khalid", "Al Siyabi", "Male", "Gastroenterology", "Marley Evening Sun-Thu", "OPD Room 6", "MHD-CONS-SPEC", 20.000),
    ("Priya", "Nair", "Female", "ENT", "Marley Morning Sun-Thu", "OPD Room 7", "MHD-CONS-SPEC", 18.000),
    ("Hassan", "Farouk", "Male", "Orthopaedics", "Marley Evening Sun-Thu", "OPD Room 8", "MHD-CONS-SPEC", 20.000),
    ("Nadia", "Rahman", "Female", "Pathology", "", "", "", 0),  # lab / reporting, no OPD schedule
]

SCHEDULES = {
    "Marley Morning Sun-Thu": ("08:00", "13:00"),
    "Marley Evening Sun-Thu": ("16:00", "21:00"),
}
WORK_DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"]  # Fri-Sat weekend (Oman)
SLOT_MIN = 15

COMPLAINTS = [
    "Fever", "Cough", "Sore Throat", "Runny Nose", "Headache", "Dizziness", "Fatigue",
    "Excessive Thirst", "Frequent Urination", "Blurred Vision", "Wheezing", "Shortness of Breath",
    "Chest Tightness", "Heartburn", "Epigastric Pain", "Nausea", "Vomiting", "Diarrhoea",
    "Lower Back Pain", "Knee Pain", "Joint Stiffness", "Weight Gain", "Cold Intolerance",
    "Sneezing", "Nasal Congestion", "Itchy Eyes", "Palpitations", "Burning Urination",
    "Pallor", "Routine Check-up",
]

# Diagnosis records: name includes ICD-10 code for readability (codification table left empty)
DIAGNOSES = {
    "T2DM": "Type 2 diabetes mellitus without complications (E11.9)",
    "HTN": "Essential (primary) hypertension (I10)",
    "DYSLIP": "Mixed hyperlipidaemia (E78.2)",
    "URTI": "Acute upper respiratory infection, unspecified (J06.9)",
    "PHARYNG": "Streptococcal pharyngitis (J02.0)",
    "ASTHMA": "Asthma, unspecified (J45.9)",
    "GERD": "Gastro-oesophageal reflux disease without oesophagitis (K21.9)",
    "HYPOTHY": "Hypothyroidism, unspecified (E03.9)",
    "LBP": "Low back pain (M54.5)",
    "KNEE_OA": "Primary osteoarthritis of knee (M17.1)",
    "IDA": "Iron deficiency anaemia, unspecified (D50.9)",
    "GE_PAED": "Gastroenteritis and colitis of unspecified origin (A09)",
    "RHINITIS": "Allergic rhinitis, unspecified (J30.4)",
    "UTI": "Urinary tract infection, site not specified (N39.0)",
    "CHECKUP": "General adult medical examination (Z00.0)",
    "CHILD_CHECK": "Routine child health examination (Z00.1)",
}

# Lab Test Templates
#   Single: (name, code, dept, rate, uom, normal_range)
#   Compound: (name, code, dept, rate, [(event, uom, range)])
LAB_SINGLE = [
    ("Fasting Blood Sugar", "MHD-LAB-FBS", "Biochemistry", 2.500, "mmol/L", "3.9 - 5.5"),
    ("HbA1c", "MHD-LAB-HBA1C", "Biochemistry", 6.000, "%", "4.0 - 5.6"),
    ("Serum Creatinine", "MHD-LAB-CREAT", "Biochemistry", 3.000, "umol/L", "60 - 110"),
    ("TSH", "MHD-LAB-TSH", "Biochemistry", 7.000, "uIU/mL", "0.4 - 4.0"),
    ("CRP", "MHD-LAB-CRP", "Biochemistry", 4.000, "mg/L", "0 - 5"),
]
LAB_COMPOUND = [
    ("Complete Blood Count", "MHD-LAB-CBC", "Haematology", 5.000, [
        ("Haemoglobin", "g/dL", "M 13.0 - 17.0 / F 12.0 - 15.5"),
        ("WBC Count", "x10^9/L", "4.0 - 11.0"),
        ("RBC Count", "x10^12/L", "4.2 - 5.9"),
        ("Platelet Count", "x10^9/L", "150 - 400"),
        ("MCV", "fL", "80 - 100"),
    ]),
    ("Lipid Profile", "MHD-LAB-LIPID", "Biochemistry", 8.000, [
        ("Total Cholesterol", "mmol/L", "< 5.2"),
        ("LDL Cholesterol", "mmol/L", "< 3.4"),
        ("HDL Cholesterol", "mmol/L", "> 1.0"),
        ("Triglycerides", "mmol/L", "< 1.7"),
    ]),
    ("Urine Routine Examination", "MHD-LAB-URINE", "Pathology", 3.000, [
        ("Urine pH", "", "4.5 - 8.0"),
        ("Specific Gravity", "", "1.005 - 1.030"),
        ("Urine Protein", "", "Negative"),
        ("Urine Glucose", "", "Negative"),
        ("Pus Cells", "/HPF", "0 - 5"),
        ("Urine RBC", "/HPF", "0 - 2"),
    ]),
]

PROCEDURES = [
    # template, item_code, dept, rate, description
    ("ECG 12-Lead", "MHD-PROC-ECG", "Cardiology", 10.000, "Resting 12-lead electrocardiogram with report"),
    ("Nebulization", "MHD-PROC-NEB", "General Medicine", 6.000, "Bronchodilator nebulization session"),
    ("Wound Dressing", "MHD-PROC-DRESS", "General Surgery", 5.000, "Simple wound cleaning and dressing"),
    ("Intramuscular Injection", "MHD-PROC-IMINJ", "General Medicine", 3.000, "Administration of IM injection"),
    ("Ear Wax Removal", "MHD-PROC-EARWAX", "ENT", 8.000, "Ear syringing / microsuction for impacted cerumen"),
]

# Medication master: generic, class (seeded ingredient leaf), strength, uom, form,
# default dosage, default duration, item_code, rate (OMR per unit pack)
MEDICATIONS = [
    ("Metformin", "Metformin", 500, "mg", "Tablet", "BID", "1 Month", "MHD-DRG-MET500", 2.500),
    ("Sitagliptin", "Sitagliptin", 100, "mg", "Tablet", "1-0-0", "1 Month", "MHD-DRG-SITA100", 14.000),
    ("Amlodipine", "Amlodipine", 5, "mg", "Tablet", "1-0-0", "1 Month", "MHD-DRG-AML5", 3.000),
    ("Losartan", "Losartan", 50, "mg", "Tablet", "1-0-0", "1 Month", "MHD-DRG-LOS50", 4.500),
    ("Atorvastatin", "Atorvastatin", 20, "mg", "Tablet", "0-0-1", "1 Month", "MHD-DRG-ATOR20", 5.000),
    ("Aspirin", "Aspirin", 81, "mg", "Tablet", "1-0-0", "1 Month", "MHD-DRG-ASP81", 1.500),
    ("Paracetamol", "Paracetamol", 500, "mg", "Tablet", "TID", "5 Day", "MHD-DRG-PCM500", 0.800),
    ("Ibuprofen", "Ibuprofen", 400, "mg", "Tablet", "TID", "5 Day", "MHD-DRG-IBU400", 1.200),
    ("Amoxicillin", "Amoxicillin", 500, "mg", "Capsule", "TID", "1 Week", "MHD-DRG-AMOX500", 2.000),
    ("Ciprofloxacin", "Ciprofloxacin", 500, "mg", "Tablet", "BID", "5 Day", "MHD-DRG-CIP500", 2.800),
    ("Cetirizine", "Cetirizine", 10, "mg", "Tablet", "Once Bedtime", "1 Week", "MHD-DRG-CET10", 1.000),
    ("Loratadine", "Loratadine", 10, "mg", "Tablet", "1-0-0", "2 Week", "MHD-DRG-LOR10", 1.300),
    ("Montelukast", "Montelukast", 10, "mg", "Tablet", "Once Bedtime", "1 Month", "MHD-DRG-MONT10", 6.000),
    ("Salbutamol", "Salbutamol", 100, "mcg", "Inhaler", "QID", "1 Month", "MHD-DRG-SALB100", 3.500),
    ("Budesonide", "Budesonide", 200, "mcg", "Inhaler", "BID", "1 Month", "MHD-DRG-BUD200", 9.000),
    ("Omeprazole", "Omeprazole", 20, "mg", "Capsule", "1-0-0", "1 Month", "MHD-DRG-OME20", 2.200),
    ("Levothyroxine", "Levothyroxine", 50, "mcg", "Tablet", "1-0-0", "1 Month", "MHD-DRG-LEVO50", 2.000),
    ("Ferrous Sulfate", "Ferrous Sulfate", 200, "mg", "Tablet", "1-0-1", "1 Month", "MHD-DRG-FESO4", 1.000),
    ("Ondansetron", "Ondansetron", 4, "mg", "Syrup", "BID", "3 Day", "MHD-DRG-OND4S", 2.500),
    ("Oral Rehydration Salts", "Oral Rehydration Salts", 20.5, "g", "Oral Powder", "QID", "3 Day", "MHD-DRG-ORS", 0.500),
]
NEW_DOSAGE_FORMS = ["Inhaler", "Oral Powder"]  # Tablet/Capsule/Syrup/Injection/Cream are seeded by Marley

# Clinical profiles drive complaints, diagnoses, departments, orders and lab results
PROFILES = {
    "T2DM": dict(dept="Diabetology", dx=["T2DM"], cx=["Excessive Thirst", "Frequent Urination", "Fatigue", "Blurred Vision"],
                 meds=["MHD-DRG-MET500", "MHD-DRG-SITA100"], labs=["MHD-LAB-HBA1C", "MHD-LAB-FBS", "MHD-LAB-CREAT"],
                 fu_labs=["MHD-LAB-HBA1C"], procs=[], adult=True, chronic=True),
    "HTN": dict(dept="Cardiology", dx=["HTN", "DYSLIP"], cx=["Headache", "Dizziness", "Palpitations"],
                meds=["MHD-DRG-AML5", "MHD-DRG-LOS50", "MHD-DRG-ATOR20"], labs=["MHD-LAB-LIPID", "MHD-LAB-CREAT"],
                fu_labs=["MHD-LAB-LIPID"], procs=["ECG 12-Lead"], adult=True, chronic=True),
    "ASTHMA": dict(dept="General Medicine", dx=["ASTHMA"], cx=["Wheezing", "Shortness of Breath", "Cough", "Chest Tightness"],
                   meds=["MHD-DRG-SALB100", "MHD-DRG-BUD200", "MHD-DRG-MONT10"], labs=["MHD-LAB-CBC"],
                   fu_labs=[], procs=["Nebulization"], adult=None, chronic=True),
    "URTI": dict(dept="General Medicine", dx=["URTI"], cx=["Fever", "Cough", "Sore Throat", "Runny Nose"],
                 meds=["MHD-DRG-PCM500", "MHD-DRG-CET10"], labs=[], fu_labs=[], procs=[], adult=True, chronic=False),
    "PHARYNG": dict(dept="ENT", dx=["PHARYNG"], cx=["Sore Throat", "Fever", "Headache"],
                    meds=["MHD-DRG-AMOX500", "MHD-DRG-PCM500"], labs=["MHD-LAB-CBC", "MHD-LAB-CRP"],
                    fu_labs=[], procs=[], adult=True, chronic=False),
    "RHINITIS": dict(dept="ENT", dx=["RHINITIS"], cx=["Sneezing", "Nasal Congestion", "Itchy Eyes", "Runny Nose"],
                     meds=["MHD-DRG-LOR10", "MHD-DRG-MONT10"], labs=[], fu_labs=[], procs=["Ear Wax Removal"], adult=True, chronic=False),
    "GERD": dict(dept="Gastroenterology", dx=["GERD"], cx=["Heartburn", "Epigastric Pain", "Nausea"],
                 meds=["MHD-DRG-OME20"], labs=["MHD-LAB-CBC"], fu_labs=[], procs=[], adult=True, chronic=True),
    "HYPOTHY": dict(dept="General Medicine", dx=["HYPOTHY"], cx=["Fatigue", "Weight Gain", "Cold Intolerance"],
                    meds=["MHD-DRG-LEVO50"], labs=["MHD-LAB-TSH", "MHD-LAB-LIPID"], fu_labs=["MHD-LAB-TSH"], procs=[], adult=True, chronic=True),
    "LBP": dict(dept="Orthopaedics", dx=["LBP"], cx=["Lower Back Pain", "Joint Stiffness"],
                meds=["MHD-DRG-IBU400", "MHD-DRG-PCM500"], labs=[], fu_labs=[], procs=["Intramuscular Injection"], adult=True, chronic=False),
    "KNEE_OA": dict(dept="Orthopaedics", dx=["KNEE_OA"], cx=["Knee Pain", "Joint Stiffness"],
                    meds=["MHD-DRG-PCM500", "MHD-DRG-IBU400"], labs=["MHD-LAB-CRP"], fu_labs=[], procs=[], adult=True, chronic=True),
    "IDA": dict(dept="Family Medicine", dx=["IDA"], cx=["Fatigue", "Pallor", "Dizziness"],
                meds=["MHD-DRG-FESO4"], labs=["MHD-LAB-CBC"], fu_labs=["MHD-LAB-CBC"], procs=[], adult=True, chronic=True),
    "UTI": dict(dept="Family Medicine", dx=["UTI"], cx=["Burning Urination", "Frequent Urination", "Fever"],
                meds=["MHD-DRG-CIP500", "MHD-DRG-PCM500"], labs=["MHD-LAB-URINE", "MHD-LAB-CBC"], fu_labs=[], procs=[], adult=True, chronic=False),
    "CHECKUP": dict(dept="Family Medicine", dx=["CHECKUP"], cx=["Routine Check-up"],
                    meds=[], labs=["MHD-LAB-CBC", "MHD-LAB-LIPID", "MHD-LAB-FBS"], fu_labs=[], procs=[], adult=True, chronic=False,
                    appt_type="Annual Health Check"),
    "GE_PAED": dict(dept="Paediatrics", dx=["GE_PAED"], cx=["Vomiting", "Diarrhoea", "Fever"],
                    meds=["MHD-DRG-ORS", "MHD-DRG-OND4S"], labs=["MHD-LAB-CBC"], fu_labs=[], procs=[], adult=False, chronic=False),
    "PAED_URTI": dict(dept="Paediatrics", dx=["URTI"], cx=["Fever", "Cough", "Runny Nose"],
                      meds=["MHD-DRG-PCM500"], labs=[], fu_labs=[], procs=[], adult=False, chronic=False),
    "CHILD_CHECK": dict(dept="Paediatrics", dx=["CHILD_CHECK"], cx=["Routine Check-up"],
                        meds=[], labs=["MHD-LAB-CBC"], fu_labs=[], procs=[], adult=False, chronic=False,
                        appt_type="Annual Health Check"),
}

DEPT_PRACTITIONER = {p[3]: f"{p[0]} {p[1]}" for p in PRACTITIONERS if p[4]}

# 50 synthetic patients: (first, last, sex, age, nationality-country, profile, marital, occupation)
PATIENTS = [
    ("Abdullah", "Al Maamari", "Male", 58, "Oman", "T2DM", "Married", "Retired teacher"),
    ("Aziza", "Al Hinai", "Female", 46, "Oman", "HYPOTHY", "Married", "Bank officer"),
    ("Saif", "Al Jabri", "Male", 63, "Oman", "HTN", "Married", "Retired"),
    ("Shamsa", "Al Saadi", "Female", 34, "Oman", "IDA", "Married", "Nurse"),
    ("Hamood", "Al Wahaibi", "Male", 41, "Oman", "LBP", "Married", "Driver"),
    ("Muna", "Al Riyami", "Female", 29, "Oman", "ASTHMA", "Single", "Engineer"),
    ("Yousuf", "Al Shukaili", "Male", 52, "Oman", "T2DM", "Married", "Business owner"),
    ("Thuraya", "Al Kharusi", "Female", 67, "Oman", "KNEE_OA", "Widow", "Homemaker"),
    ("Talal", "Al Ghafri", "Male", 37, "Oman", "GERD", "Married", "Accountant"),
    ("Badriya", "Al Mukhaini", "Female", 55, "Oman", "HTN", "Married", "Teacher"),
    ("Nasser", "Al Abri", "Male", 24, "Oman", "PHARYNG", "Single", "Student"),
    ("Huda", "Al Farsi", "Female", 31, "Oman", "UTI", "Married", "Pharmacist"),
    ("Majid", "Al Amri", "Male", 45, "Oman", "CHECKUP", "Married", "Civil servant"),
    ("Rahma", "Al Battashi", "Female", 39, "Oman", "RHINITIS", "Married", "HR manager"),
    ("Sultan", "Al Hashmi", "Male", 70, "Oman", "HTN", "Married", "Retired"),
    ("Zahra", "Al Mahrouqi", "Female", 26, "Oman", "URTI", "Single", "Graphic designer"),
    ("Hilal", "Al Habsi", "Male", 49, "Oman", "T2DM", "Married", "Fisherman"),
    ("Asma", "Al Sinani", "Female", 42, "Oman", "GERD", "Divorced", "Lecturer"),
    ("Ibrahim", "Al Naabi", "Male", 33, "Oman", "URTI", "Married", "Police officer"),
    ("Khadija", "Al Tobi", "Female", 61, "Oman", "T2DM", "Married", "Homemaker"),
    ("Arjun", "Pillai", "Male", 44, "India", "HTN", "Married", "Site engineer"),
    ("Lakshmi", "Varma", "Female", 38, "India", "HYPOTHY", "Married", "School teacher"),
    ("Mohammed", "Iqbal", "Male", 36, "Pakistan", "LBP", "Married", "Electrician"),
    ("Ayesha", "Siddiqui", "Female", 28, "Pakistan", "IDA", "Married", "Homemaker"),
    ("Jose", "Santos", "Male", 40, "Philippines", "GERD", "Married", "Chef"),
    ("Maria", "Reyes", "Female", 32, "Philippines", "ASTHMA", "Single", "Sales associate"),
    ("Omar", "Hassan", "Male", 50, "Egypt", "T2DM", "Married", "Architect"),
    ("Nour", "Mahmoud", "Female", 27, "Egypt", "RHINITIS", "Single", "Marketing executive"),
    ("James", "Whitfield", "Male", 57, "United Kingdom", "CHECKUP", "Married", "Consultant"),
    ("Sarah", "Collins", "Female", 35, "United Kingdom", "UTI", "Married", "Teacher"),
    ("Ravi", "Shankar", "Male", 47, "India", "KNEE_OA", "Married", "Supervisor"),
    ("Deepa", "Krishnan", "Female", 30, "India", "PHARYNG", "Married", "IT analyst"),
    ("Imran", "Qureshi", "Male", 54, "Pakistan", "HTN", "Married", "Shop owner"),
    ("Grace", "Mendoza", "Female", 45, "Philippines", "CHECKUP", "Married", "Nurse"),
    ("Kareem", "Abdelaziz", "Male", 31, "Jordan", "URTI", "Single", "Software developer"),
    ("Layla", "Haddad", "Female", 48, "Lebanon", "HYPOTHY", "Married", "Interior designer"),
    ("Faisal", "Al Mazrui", "Male", 65, "Oman", "KNEE_OA", "Married", "Retired"),
    ("Salma", "Al Balushi", "Female", 36, "Oman", "CHECKUP", "Married", "Lawyer"),
    ("Hamed", "Al Rashdi", "Male", 59, "Oman", "T2DM", "Married", "Farmer"),
    ("Noora", "Al Zadjali", "Female", 23, "Oman", "ASTHMA", "Single", "Student"),
    ("Hamza", "Al Maamari", "Male", 8, "Oman", "PAED_URTI", "Single", "Student"),
    ("Reem", "Al Hinai", "Female", 5, "Oman", "GE_PAED", "Single", ""),
    ("Fahad", "Al Saadi", "Male", 3, "Oman", "CHILD_CHECK", "Single", ""),
    ("Jana", "Al Riyami", "Female", 11, "Oman", "ASTHMA", "Single", "Student"),
    ("Aarav", "Pillai", "Male", 7, "India", "GE_PAED", "Single", "Student"),
    ("Zainab", "Iqbal", "Female", 2, "Pakistan", "CHILD_CHECK", "Single", ""),
    ("Yahya", "Al Habsi", "Male", 13, "Oman", "PAED_URTI", "Single", "Student"),
    ("Mira", "Santos", "Female", 9, "Philippines", "PAED_URTI", "Single", "Student"),
    ("Adam", "Hassan", "Male", 4, "Egypt", "GE_PAED", "Single", ""),
    ("Lina", "Al Shukaili", "Female", 14, "Oman", "RHINITIS", "Single", "Student"),
]

# Family links: (child index, parent index, relation from the child's record)
FAMILY = [
    (40, 0, "Father"), (41, 1, "Mother"), (42, 3, "Mother"), (43, 5, "Mother"),
    (44, 20, "Father"), (45, 23, "Mother"), (46, 16, "Father"), (47, 24, "Father"),
    (48, 26, "Father"), (49, 6, "Father"), (44, 21, "Mother"), (45, 22, "Father"),
]

BLOOD_GROUPS = ["O Positive"] * 8 + ["A Positive"] * 6 + ["B Positive"] * 6 + ["AB Positive"] * 2 + [
    "O Negative", "A Negative", "B Negative"]

ALLERGY_NOTES = {3: "Penicillin (rash)", 9: "Sulfa drugs", 25: "Dust mites, cat dander", 36: "Shellfish",
                 13: "Pollen (seasonal)", 47: "Peanuts"}
# Patients with a stated penicillin allergy must never get amoxicillin -> PHARYNG profile avoids index 3.

# Inpatients: (patient index, admit status, ward bed, LOS days, practitioner dept, reason)
INPATIENTS = [
    (5, "Admitted", "Ward A Bed 01", 3, "General Medicine", "Acute asthma exacerbation, nebulization and IV steroids"),
    (41, "Admitted", "Ward A Bed 02", 2, "Paediatrics", "Dehydration secondary to gastroenteritis, IV fluids"),
    (14, "Admission Scheduled", "", 2, "Cardiology", "Elective admission for BP control and cardiac work-up"),
    (19, "Admission Scheduled", "", 2, "Diabetology", "Elective admission for insulin initiation and education"),
]


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------

def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow(["" if v is None else v for v in r])


def fmt3(x):
    return f"{x:.3f}"


def child_block(parent_values, children):
    """Expand one parent row + several child tables into Frappe importer rows.

    parent_values: list of parent column values
    children: list of (n_cols, rows) per child table, in header order
    Returns list of rows.
    """
    n = max([1] + [len(rows) for _, rows in children])
    out = []
    for i in range(n):
        row = list(parent_values) if i == 0 else [""] * len(parent_values)
        for ncols, rows in children:
            row += list(rows[i]) if i < len(rows) else [""] * ncols
        out.append(row)
    return out


class Calendar:
    """Keeps practitioner & patient appointments non-overlapping."""

    def __init__(self):
        self.prac = {}  # (prac, date) -> set(slot index)
        self.patient_days = {}  # patient -> set(date)

    def slots_for(self, schedule):
        start, end = SCHEDULES[schedule]
        s = dt.datetime.strptime(start, "%H:%M")
        e = dt.datetime.strptime(end, "%H:%M")
        out = []
        while s < e:
            out.append(s.strftime("%H:%M:%S"))
            s += dt.timedelta(minutes=SLOT_MIN)
        return out

    def book(self, rng, prac, schedule, date, patient, duration):
        if date in self.patient_days.get(patient, set()):
            return None
        need = max(1, duration // SLOT_MIN)
        slots = self.slots_for(schedule)
        used = self.prac.setdefault((prac, date), set())
        starts = [i for i in range(len(slots) - need + 1) if all((i + k) not in used for k in range(need))]
        if not starts:
            return None
        i = rng.choice(starts)
        for k in range(need):
            used.add(i + k)
        self.patient_days.setdefault(patient, set()).add(date)
        return slots[i]


def working_days(start, end):
    d = start
    out = []
    while d <= end:
        if d.strftime("%A") in WORK_DAYS:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def nearest_workday(d, forward=True):
    step = dt.timedelta(days=1 if forward else -1)
    while d.strftime("%A") not in WORK_DAYS:
        d += step
    return d


# --------------------------------------------------------------------------------------
# lab result synthesis
# --------------------------------------------------------------------------------------

def lab_results(rng, code, profile, sex, age, visit_no):
    r = lambda a, b, nd=1: round(rng.uniform(a, b), nd)  # noqa: E731
    control = visit_no > 1  # follow-up results improve
    if code == "MHD-LAB-HBA1C":
        v = r(6.6, 7.4) if control else r(7.4, 9.6)
        return [("HbA1c", v if profile == "T2DM" else r(4.8, 5.6))]
    if code == "MHD-LAB-FBS":
        return [("Fasting Blood Sugar", r(7.2, 11.5) if profile == "T2DM" else r(4.3, 5.4))]
    if code == "MHD-LAB-CREAT":
        return [("Serum Creatinine", int(rng.uniform(62, 118)))]
    if code == "MHD-LAB-TSH":
        if profile == "HYPOTHY":
            return [("TSH", r(1.8, 3.6, 2) if control else r(7.5, 14.0, 2))]
        return [("TSH", r(0.8, 3.2, 2))]
    if code == "MHD-LAB-CRP":
        return [("CRP", r(18, 65) if profile == "PHARYNG" else r(1, 9))]
    if code == "MHD-LAB-CBC":
        if profile == "IDA":
            hb = r(10.8, 12.2) if control else r(8.6, 10.4)
            mcv = int(rng.uniform(72, 79)) if not control else int(rng.uniform(78, 84))
        else:
            hb = r(13.2, 16.4) if sex == "Male" else r(12.0, 14.6)
            if age < 12:
                hb = r(11.2, 13.4)
            mcv = int(rng.uniform(82, 96))
        wbc = r(11.5, 16.8) if profile in ("PHARYNG", "UTI", "GE_PAED") else r(5.0, 9.8)
        return [("Haemoglobin", hb), ("WBC Count", wbc), ("RBC Count", r(4.1, 5.6, 2)),
                ("Platelet Count", int(rng.uniform(180, 380))), ("MCV", mcv)]
    if code == "MHD-LAB-LIPID":
        hi = profile in ("HTN",) and not control
        return [("Total Cholesterol", r(5.6, 6.8) if hi else r(3.9, 5.1)),
                ("LDL Cholesterol", r(3.6, 4.6) if hi else r(1.9, 3.2)),
                ("HDL Cholesterol", r(0.8, 1.1) if hi else r(1.1, 1.7)),
                ("Triglycerides", r(1.8, 2.9) if hi else r(0.8, 1.6))]
    if code == "MHD-LAB-URINE":
        uti = profile == "UTI"
        return [("Urine pH", r(5.5, 7.0)), ("Specific Gravity", rng.choice(["1.010", "1.015", "1.020", "1.025"])),
                ("Urine Protein", "Trace" if uti else "Negative"), ("Urine Glucose", "Negative"),
                ("Pus Cells", f"{rng.randint(20, 40)}-{rng.randint(41, 60)}" if uti else "1-2"),
                ("Urine RBC", f"{rng.randint(3, 6)}-{rng.randint(7, 10)}" if uti else "0-1")]
    return []


def vitals(rng, profile, age, sex):
    if age < 12:
        h = round(0.85 + age * 0.06 + rng.uniform(-0.04, 0.04), 2)
        w = round(10 + age * 2.6 + rng.uniform(-2, 2), 1)
        sys_, dia = rng.randint(90, 108), rng.randint(55, 68)
        pulse = rng.randint(88, 120)
        rr = rng.randint(20, 28)
    else:
        h = round(rng.uniform(1.68, 1.84) if sex == "Male" else rng.uniform(1.52, 1.68), 2)
        bmi_target = rng.uniform(26, 33) if profile in ("T2DM", "HTN", "KNEE_OA", "HYPOTHY") else rng.uniform(21, 27)
        w = round(bmi_target * h * h, 1)
        if profile == "HTN":
            sys_, dia = rng.randint(142, 166), rng.randint(88, 102)
        else:
            sys_, dia = rng.randint(108, 132), rng.randint(68, 84)
        pulse = rng.randint(66, 92)
        rr = rng.randint(14, 18)
    febrile = profile in ("URTI", "PHARYNG", "UTI", "GE_PAED", "PAED_URTI")
    temp = round(rng.uniform(37.9, 39.2) if febrile else rng.uniform(36.5, 37.2), 1)
    if profile == "ASTHMA":
        rr += rng.randint(2, 6)
    return dict(temperature=temp, pulse=pulse, respiratory_rate=rr, bp_systolic=sys_, bp_diastolic=dia,
                height=h, weight=w)


# --------------------------------------------------------------------------------------
# main build
# --------------------------------------------------------------------------------------

def build(out, company, abbr, anchor):
    rng = random.Random(SEED)
    os.makedirs(out, exist_ok=True)
    su = lambda n: f"{n} - {abbr}"  # noqa: E731  service unit full name
    manifest = {"company": company, "abbr": abbr, "anchor": anchor.isoformat(), "files": []}

    def emit(fname, header, rows, doctype, mode="Insert New Records", loader_only=False, note=""):
        write_csv(os.path.join(out, fname), header, rows)
        manifest["files"].append(dict(file=fname, doctype=doctype, import_type=mode, rows=len(rows),
                                      loader_only=loader_only, note=note))

    # ---- Tier 0: ERPNext / Frappe prerequisites --------------------------------------
    emit("00_uom.csv", ["uom_name", "must_be_whole_number"], UOMS, "UOM")
    emit("01_customer_group.csv", ["customer_group_name", "parent_customer_group", "is_group"],
         [("Patients", "All Customer Groups", 0)], "Customer Group")
    emit("02_territory.csv", ["territory_name", "parent_territory", "is_group"],
         [("Oman", "All Territories", 0)], "Territory")
    emit("03_item_group.csv", ["item_group_name", "parent_item_group", "is_group"],
         [("Healthcare Services", "All Item Groups", 0)], "Item Group",
         note="'Laboratory' and 'Drug' item groups are seeded by Marley on install")
    emit("04_item_services.csv",
         ["item_code", "item_name", "item_group", "stock_uom", "is_stock_item", "is_sales_item",
          "is_purchase_item", "include_item_in_manufacturing", "standard_rate", "description"],
         [(c, n, "Healthcare Services", "Nos", 0, 1, 0, 0, fmt3(r), d) for c, n, r, d in SERVICE_ITEMS],
         "Item", note="standard_rate creates an Item Price in the default selling price list")

    # ---- Tier 1: Healthcare masters without cross-links ------------------------------
    emit("05_medical_department.csv", ["department"], [(d,) for d in NEW_DEPARTMENTS], "Medical Department",
         note="Marley seeds 23 departments on install (Cardiology, Diabetology, ENT, ...); only these three are new")
    emit("06_dosage_form.csv", ["dosage_form"], [(d,) for d in NEW_DOSAGE_FORMS], "Dosage Form")
    emit("07_lab_test_uom.csv", ["lab_test_uom", "uom_description"], [(u, "") for u in LAB_TEST_UOMS], "Lab Test UOM")
    emit("08_complaint.csv", ["complaints"], [(c,) for c in COMPLAINTS], "Complaint")
    emit("09_diagnosis.csv", ["diagnosis"], [(d,) for d in DIAGNOSES.values()], "Diagnosis")
    emit("10_appointment_type.csv", ["appointment_type", "default_duration", "allow_booking_for", "color"],
         APPOINTMENT_TYPES and [(n, d, "Practitioner", c) for n, d, c in APPOINTMENT_TYPES], "Appointment Type")

    # Practitioner schedules (one child row per bookable slot)
    rows = []
    for name, (start, end) in SCHEDULES.items():
        slots = []
        for day in WORK_DAYS:
            s = dt.datetime.strptime(start, "%H:%M")
            e = dt.datetime.strptime(end, "%H:%M")
            while s < e:
                nxt = s + dt.timedelta(minutes=SLOT_MIN)
                slots.append((day, s.strftime("%H:%M:%S"), nxt.strftime("%H:%M:%S"), SLOT_MIN, 1))
                s = nxt
        rows += child_block([name], [(5, slots)])
    emit("11_practitioner_schedule.csv",
         ["schedule_name", "time_slots.day", "time_slots.from_time", "time_slots.to_time", "time_slots.duration",
          "time_slots.maximum_appointments"],
         rows, "Practitioner Schedule")

    emit("12_service_unit_type.csv",
         ["service_unit_type", "allow_appointments", "inpatient_occupancy", "is_billable", "item_code",
          "item_group", "rate", "uom", "no_of_hours"],
         [(n, a, i, b, ic, "Healthcare Services" if ic else "", fmt3(r) if r != "" else "", u, h)
          for n, a, i, b, ic, r, u, h in SERVICE_UNIT_TYPES],
         "Healthcare Service Unit Type", note="Billable bed type auto-creates its Item")

    # Service unit tree. In-file parents are referenced by unit name (tree alias);
    # the company root is referenced by its full name.
    root = su("All Healthcare Service Units")
    hsu = [("Marley Clinic", root, 1, "")]
    hsu += [("Marley OPD", "Marley Clinic", 1, ""), ("Marley Ward A", "Marley Clinic", 1, "")]
    for i in range(1, 9):
        hsu.append((f"OPD Room {i}", "Marley OPD", 0, "Consultation Room"))
    hsu.append(("Procedure Room 1", "Marley OPD", 0, "Procedure Room"))
    hsu.append(("Main Laboratory", "Marley Clinic", 0, "Laboratory"))
    for b in range(1, 7):
        hsu.append((f"Ward A Bed {b:02d}", "Marley Ward A", 0, "General Ward Bed"))
    emit("13_healthcare_service_unit.csv",
         ["healthcare_service_unit_name", "parent_healthcare_service_unit", "is_group", "service_unit_type", "company"],
         [(n, p, g, t, company) for n, p, g, t in hsu], "Healthcare Service Unit",
         note=f"Tree. Root '{root}' is created by Marley per company. Names get the ' - {abbr}' suffix.")

    # ---- Tier 2: masters that create Items ------------------------------------------
    rows = []
    for name, code, dept, rate, uom, rng_ in LAB_SINGLE:
        rows.append((name, code, "Laboratory", dept, "Single", 1, fmt3(rate), uom, rng_, "", "", ""))
    for name, code, dept, rate, events in LAB_COMPOUND:
        parent = [name, code, "Laboratory", dept, "Compound", 1, fmt3(rate), "", ""]
        rows += child_block(parent, [(3, events)])
    emit("14_lab_test_template.csv",
         ["lab_test_name", "lab_test_code", "lab_test_group", "department", "lab_test_template_type",
          "is_billable", "lab_test_rate", "lab_test_uom", "lab_test_normal_range",
          "normal_test_templates.lab_test_event", "normal_test_templates.lab_test_uom",
          "normal_test_templates.normal_range"],
         rows, "Lab Test Template", note="Each template auto-creates a service Item (code = lab_test_code)")

    emit("15_clinical_procedure_template.csv",
         ["template", "item_code", "item_group", "medical_department", "is_billable", "rate", "description"],
         [(t, c, "Healthcare Services", d, 1, fmt3(r), desc) for t, c, d, r, desc in PROCEDURES],
         "Clinical Procedure Template", note="Each template auto-creates a service Item")

    emit("16_medication.csv",
         ["generic_name", "medication_class", "strength", "strength_uom", "dosage_form",
          "default_prescription_dosage", "default_prescription_duration", "price_list",
          "linked_items.item_code", "linked_items.item_group", "linked_items.stock_uom",
          "linked_items.rate", "linked_items.is_billable"],
         [(g, c, s, u, f, ds, du, "Standard Selling", ic, "Drug", "Nos", fmt3(r), 1)
          for g, c, s, u, f, ds, du, ic, r in MEDICATIONS],
         "Medication",
         note="medication_class uses Marley's seeded ingredient classes; linked items are created as stock Items")

    # ---- Tier 3: practitioners -------------------------------------------------------
    rows = []
    for i, (fn, ln, g, dept, sched, room, item, charge) in enumerate(PRACTITIONERS):
        mobile = f"+968 9{(7100000 + i * 13579) % 10000000:07d}"
        parent = [fn, ln, g, dept, "Active", "Internal", mobile,
                  item, fmt3(charge) if item else "", "MHD-IP-VISIT" if item else "", fmt3(15) if item else ""]
        children = [(2, [(sched, su(room))])] if sched else [(2, [])]
        rows += child_block(parent, children)
    emit("17_healthcare_practitioner.csv",
         ["first_name", "last_name", "gender", "department", "status", "practitioner_type", "mobile_phone",
          "op_consulting_charge_item", "op_consulting_charge", "inpatient_visit_charge_item",
          "inpatient_visit_charge", "practitioner_schedules.schedule", "practitioner_schedules.service_unit"],
         rows, "Healthcare Practitioner",
         note="IDs come from the HLC-PRAC-.YYYY.- naming series; later files use '<first> <last>'")

    # ---- Tier 4: patients ------------------------------------------------------------
    rows = []
    patient_names = []
    for i, (fn, ln, sex, age, country, prof, marital, occ) in enumerate(PATIENTS):
        dob = anchor.replace(year=anchor.year - age) - dt.timedelta(days=rng.randint(15, 340))
        full = f"{fn} {ln}"
        patient_names.append(full)
        mobile = f"+968 9{(2000000 + i * 104729) % 10000000:07d}"
        email = f"{fn.lower()}.{ln.lower().replace(' ', '')}.demo@example.com" if age >= 18 else ""
        hist = {
            "T2DM": "Type 2 diabetes, diagnosed 4 years ago", "HTN": "Hypertension, dyslipidaemia",
            "HYPOTHY": "Hypothyroidism", "ASTHMA": "Bronchial asthma since childhood",
            "KNEE_OA": "Osteoarthritis both knees", "GERD": "Recurrent dyspepsia", "IDA": "Low haemoglobin on routine test",
        }.get(prof, "")
        rows.append((fn, ln, sex, dob.isoformat(), rng.choice(BLOOD_GROUPS), country, "en",
                     mobile, email, f"DEMO-{i + 1:04d}", marital if age >= 18 else "Single", occ,
                     ALLERGY_NOTES.get(i, ""), hist, "Patients", "Oman", "Email" if email else "Print", 0,
                     "Active", f"Synthetic demo patient. Profile: {prof}"))
    emit("18_patient.csv",
         ["first_name", "last_name", "sex", "dob", "blood_group", "country", "language", "mobile", "email",
          "uid", "marital_status", "occupation", "allergies", "medical_history", "customer_group", "territory",
          "report_preference", "invite_user", "status", "patient_details"],
         rows, "Patient",
         note="With Healthcare Settings > Patient Name By = 'Patient Name', each ID equals '<first> <last>'.")

    rows = []
    fam = {}
    for c, p, rel in FAMILY:
        fam.setdefault(c, []).append((patient_names[p], rel))
    for c, rels in fam.items():
        rows += child_block([patient_names[c]], [(2, rels)])
    emit("19_patient_relation_update.csv", ["name", "patient_relation.patient", "patient_relation.relation"],
         rows, "Patient", mode="Update Existing Records",
         note="Second pass: links children to parents. 'name' = Patient ID.")

    # ---- Tier 5: transactions --------------------------------------------------------
    cal = Calendar()
    start = anchor - dt.timedelta(days=120)
    past_days = working_days(start, anchor - dt.timedelta(days=3))
    future_days = working_days(anchor + dt.timedelta(days=1), anchor + dt.timedelta(days=21))
    prac_meta = {f"{p[0]} {p[1]}": p for p in PRACTITIONERS}

    appts, encs, vit, labs, procs = [], [], [], [], []
    apt_no = enc_no = 0

    def book(pidx, prac, appt_type, date, status, duration=None):
        nonlocal apt_no
        sched = prac_meta[prac][4]
        duration = duration or dict((n, d) for n, d, _ in APPOINTMENT_TYPES)[appt_type]
        t = cal.book(rng, prac, sched, date, pidx, duration)
        if not t:
            return None
        apt_no += 1
        ref = f"APT-{apt_no:04d}"
        appts.append(dict(ref=ref, patient=patient_names[pidx], appointment_type=appt_type, appointment_for="Practitioner",
                          practitioner=prac, department=prac_meta[prac][3], service_unit=su(prac_meta[prac][5]),
                          appointment_date=date.isoformat(), appointment_time=t, duration=duration, status=status,
                          company=company))
        return appts[-1]

    def add_encounter(pidx, prof_key, appt, date, time, visit_no, ip_admission=False):
        nonlocal enc_no
        p = PATIENTS[pidx]
        prof = PROFILES[prof_key]
        enc_no += 1
        ref = f"ENC-{enc_no:04d}"
        prac = appt["practitioner"] if appt else DEPT_PRACTITIONER[prof["dept"]]
        n_cx = rng.randint(1, min(3, len(prof["cx"])))
        symptoms = rng.sample(prof["cx"], n_cx)
        diagnosis = [DIAGNOSES[k] for k in prof["dx"]]
        meds = list(prof["meds"])
        if ip_admission:
            lab_codes = list(prof["labs"]) or ["MHD-LAB-CBC"]
        else:
            lab_codes = list(prof["labs"]) if visit_no == 1 else list(prof["fu_labs"])
        proc_list = list(prof["procs"]) if (visit_no == 1 and prof["procs"] and rng.random() < 0.7) else []
        if ip_admission and prof_key == "ASTHMA":
            proc_list = ["Nebulization"]
        drug_rows = []
        for ic in meds:
            m = next(x for x in MEDICATIONS if x[7] == ic)
            drug_rows.append((ic, m[4], m[5], m[6], ""))
        note = {1: "New visit. History taken, examined, plan discussed with patient.",
                2: "Follow-up. Adherent to medication; reviewing results.",
                3: "Follow-up. Stable; continue current plan."}.get(visit_no, "Follow-up visit.")
        if ip_admission:
            note = "Assessed in OPD; admission advised."
        encs.append(dict(ref=ref, appt_ref=appt["ref"] if appt else "", patient=patient_names[pidx],
                         practitioner=prac, appointment_type=appt["appointment_type"] if appt else "Consultation",
                         medical_department=prac_meta[prac][3], encounter_date=date.isoformat(), encounter_time=time,
                         company=company, encounter_comment=note, symptoms=symptoms, diagnosis=diagnosis,
                         drugs=drug_rows, labs=lab_codes, procs=proc_list))
        # vitals
        v = vitals(rng, prof_key, p[3], p[2])
        vit.append(dict(patient=patient_names[pidx], signs_date=date.isoformat(), signs_time=time, company=company,
                        appt_ref=appt["ref"] if appt else "", enc_ref=ref, **v))
        # lab results (only for encounters at least 2 days old -> Completed, else left Draft)
        age_days = (anchor - date).days
        for code in lab_codes:
            res = lab_results(rng, code, prof_key, p[2], p[3], visit_no)
            status = "Completed" if age_days >= 2 else "Draft"
            for event, value in res:
                labs.append(dict(enc_ref=ref, template=next(t[0] for t in LAB_SINGLE + LAB_COMPOUND if t[1] == code),
                                 lab_test_name=event, result_value=value, status=status,
                                 result_date=(date + dt.timedelta(days=1)).isoformat()))
        for proc in proc_list:
            procs.append(dict(enc_ref=ref, procedure_template=proc, start_date=date.isoformat(),
                              start_time=time, status="Completed"))
        return ref

    ip_idx = {x[0] for x in INPATIENTS}
    for pidx, p in enumerate(PATIENTS):
        prof_key = p[5]
        prof = PROFILES[prof_key]
        prac = DEPT_PRACTITIONER[prof["dept"]]
        n_past = (rng.choice([2, 3, 3]) if prof["chronic"] else rng.choice([1, 1, 2]))
        if pidx in ip_idx:
            n_past = max(1, n_past - 1)
        # first visit somewhere in the first half of the window
        d = rng.choice(past_days[: len(past_days) // 2])
        visit_no = 0
        while visit_no < n_past:
            visit_no += 1
            appt_type = prof.get("appt_type", "Consultation") if visit_no == 1 else "Follow-up"
            if visit_no == 1 and prof["procs"] and prof_key in ("HTN",):
                appt_type = "Consultation"
            appt = None
            for _ in range(15):
                appt = book(pidx, prac, appt_type, d, "Checked Out")
                if appt:
                    break
                d = nearest_workday(d + dt.timedelta(days=1))
            if not appt:
                break
            add_encounter(pidx, prof_key, appt, d, appt["appointment_time"], visit_no)
            d = nearest_workday(d + dt.timedelta(days=rng.randint(14, 35)))
            if d > past_days[-1]:
                break
        # a few no-shows / cancellations
        r = rng.random()
        if r < 0.10:
            nd = rng.choice(past_days[len(past_days) // 2:])
            book(pidx, prac, "Follow-up", nd, "No Show")
        elif r < 0.18:
            nd = rng.choice(future_days)
            book(pidx, prac, "Follow-up", nd, "Cancelled")
        # upcoming follow-ups for chronic patients + some acute
        if prof["chronic"] or rng.random() < 0.25:
            for _ in range(10):
                nd = rng.choice(future_days)
                if book(pidx, prac, "Follow-up", nd, "Scheduled"):
                    break

    # walk-in today ("Open") and checked-in queue for the dashboard
    today = nearest_workday(anchor, forward=False) if anchor.strftime("%A") not in WORK_DAYS else anchor
    if today == anchor:
        for pidx, status in [(10, "Checked In"), (15, "Checked In"), (18, "Open"), (31, "Open"), (34, "Confirmed")]:
            prof = PROFILES[PATIENTS[pidx][5]]
            for _ in range(5):
                if book(pidx, DEPT_PRACTITIONER[prof["dept"]], "Follow-up", anchor, status):
                    break

    # inpatient admissions: an admission encounter (no appointment) 1-2 days ago
    ip_rows = []
    for pidx, status, bed, los, dept, reason in INPATIENTS:
        prof_key = PATIENTS[pidx][5]
        adm_date = nearest_workday(anchor - dt.timedelta(days=1 if status == "Admitted" else 0), forward=False)
        prac = DEPT_PRACTITIONER[dept]
        ref = add_encounter(pidx, prof_key, None, adm_date, "10:30:00", 99, ip_admission=True)
        check_in = f"{adm_date.isoformat()} 13:00:00" if status == "Admitted" else ""
        ip_rows.append(dict(patient=patient_names[pidx], admission_encounter_ref=ref, status=status,
                            medical_department=dept, primary_practitioner=prac, admission_practitioner=prac,
                            admission_service_unit_type="General Ward Bed", expected_length_of_stay=los,
                            admission_instruction=reason, bed=su(bed) if bed else "", check_in=check_in,
                            company=company))

    # ---- write transactions ------------------------------------------------------------
    appts.sort(key=lambda a: (a["appointment_date"], a["appointment_time"]))
    emit("20_patient_appointment.csv",
         ["_ref", "patient", "appointment_type", "appointment_for", "practitioner", "department", "service_unit",
          "appointment_date", "appointment_time", "duration", "status", "company"],
         [(a["ref"], a["patient"], a["appointment_type"], a["appointment_for"], a["practitioner"], a["department"],
           a["service_unit"], a["appointment_date"], a["appointment_time"], a["duration"], a["status"], a["company"])
          for a in appts], "Patient Appointment", loader_only=True,
         note="Practitioners are referenced by full name; Marley names them HLC-PRAC-.YYYY.-, so the loader maps "
              "them. It also pins historic statuses (Checked Out -> Closed by the encounter).")

    encs.sort(key=lambda e: (e["encounter_date"], e["encounter_time"]))
    rows = []
    for e in encs:
        parent = [e["ref"], e["appt_ref"], e["patient"], e["practitioner"], e["appointment_type"], e["medical_department"],
                  e["encounter_date"], e["encounter_time"], e["company"], e["encounter_comment"]]
        rows += child_block(parent, [
            (1, [(s,) for s in e["symptoms"]]),
            (1, [(d,) for d in e["diagnosis"]]),
            (5, e["drugs"]),
            (1, [(next(t[0] for t in LAB_SINGLE + LAB_COMPOUND if t[1] == c),) for c in e["labs"]]),
            (2, [(p, 1) for p in e["procs"]]),
        ])
    emit("21_patient_encounter.csv",
         ["_ref", "_appointment_ref", "patient", "practitioner", "appointment_type", "medical_department",
          "encounter_date", "encounter_time", "company", "encounter_comment",
          "symptoms.complaint", "diagnosis.diagnosis",
          "drug_prescription.drug_code", "drug_prescription.dosage_form", "drug_prescription.dosage",
          "drug_prescription.period", "drug_prescription.comment",
          "lab_test_prescription.lab_test_code",
          "procedure_prescription.procedure", "procedure_prescription.no_of_sessions"],
         rows, "Patient Encounter", loader_only=True,
         note="Submitted by the loader; submission creates Service Requests and Medication Requests.")

    vit.sort(key=lambda v: (v["signs_date"], v["signs_time"]))
    emit("22_vital_signs.csv",
         ["_appointment_ref", "_encounter_ref", "patient", "signs_date", "signs_time", "temperature", "pulse",
          "respiratory_rate", "bp_systolic", "bp_diastolic", "height", "weight", "company"],
         [(v["appt_ref"], v["enc_ref"], v["patient"], v["signs_date"], v["signs_time"], v["temperature"], v["pulse"],
           v["respiratory_rate"], v["bp_systolic"], v["bp_diastolic"], v["height"], v["weight"], v["company"])
          for v in vit], "Vital Signs", loader_only=True, note="Linked to appointment + encounter, submitted")

    emit("23_lab_test_results.csv",
         ["_encounter_ref", "template", "lab_test_name", "result_value", "status", "result_date"],
         [(x["enc_ref"], x["template"], x["lab_test_name"], x["result_value"], x["status"], x["result_date"]) for x in labs],
         "Lab Test", loader_only=True,
         note="Long format, one row per result. Loader creates the Lab Test from the encounter's Service Request, "
              "fills results and submits Completed ones.")

    emit("24_clinical_procedure.csv",
         ["_encounter_ref", "procedure_template", "start_date", "start_time", "status"],
         [(x["enc_ref"], x["procedure_template"], x["start_date"], x["start_time"], x["status"]) for x in procs],
         "Clinical Procedure", loader_only=True, note="Created against the encounter's Service Request")

    emit("25_inpatient_record.csv",
         ["patient", "_admission_encounter_ref", "status", "medical_department", "primary_practitioner",
          "admission_practitioner", "admission_service_unit_type", "expected_length_of_stay",
          "admission_instruction", "_bed", "_check_in", "company"],
         [(x["patient"], x["admission_encounter_ref"], x["status"], x["medical_department"], x["primary_practitioner"],
           x["admission_practitioner"], x["admission_service_unit_type"], x["expected_length_of_stay"],
           x["admission_instruction"], x["bed"], x["check_in"], x["company"]) for x in ip_rows],
         "Inpatient Record", loader_only=True,
         note="Created via Marley's create_inpatient_record / admit_patient so bed occupancy and patient status update")

    stats = dict(patients=len(PATIENTS), appointments=len(appts), encounters=len(encs), vital_signs=len(vit),
                 lab_tests=len({(x["enc_ref"], x["template"]) for x in labs}), lab_result_rows=len(labs),
                 clinical_procedures=len(procs), inpatient_records=len(ip_rows),
                 appointment_status={s: sum(1 for a in appts if a["status"] == s)
                                     for s in sorted({a["status"] for a in appts})})
    manifest["stats"] = stats
    with open(os.path.join(out, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "marley_demo_data", "data"))
    ap.add_argument("--company", default="Marley Health Demo")
    ap.add_argument("--abbr", default="MHD")
    ap.add_argument("--anchor", default=dt.date.today().isoformat(), help="'today' for the dataset (YYYY-MM-DD)")
    a = ap.parse_args()
    m = build(a.out, a.company, a.abbr, dt.date.fromisoformat(a.anchor))
    print(json.dumps(m["stats"], indent=2))
