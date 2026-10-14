# Marley Demo Data (v16.6.1)

Synthetic, 50-patient demo dataset for **Frappe v16 + ERPNext v16 + Marley Health (healthcare) v16.6.1**,
shipped as dependency-ordered CSV import files plus a bench loader that creates the clinical
transactions through Marley's own controllers.

All people, phone numbers, IDs (`DEMO-0001`…) and e-mails (`@example.com`) are fictitious.
Context: Oman clinic — OMR prices, Sun–Thu working week (Fri–Sat weekend), +968 numbers.

## What's in it

| Area | Records |
|---|---|
| Patients | 50 (40 adults, 10 children), 12 family links, 6 with allergy notes |
| Practitioners | 9 across 9 departments (8 with OPD schedules + rooms, 1 pathologist) |
| Appointments | 137 — 96 completed, 30 scheduled, 5 today (queue), 3 no-show, 3 cancelled |
| Encounters (submitted) | 100 with complaints, ICD-10-labelled diagnoses, prescriptions and orders |
| Auto-created by Marley | 111 Service Requests, 184 Medication Requests, ~300 Patient Medical Records, 137 calendar Events, 50 Customers + Contacts |
| Vital Signs (submitted) | 100, profile-consistent (hypertensive BP, febrile temps, paediatric norms) |
| Lab Tests | 103 against the encounters' Service Requests (96 completed, 7 draft = recent), 284 result values |
| Clinical Procedures | 8 (ECG, nebulization, IM injection, ear wax removal) |
| Inpatient | 4 — 2 admitted to Ward A beds, 2 admission scheduled |
| Masters | 3 depts, 30 complaints, 16 diagnoses, 8 lab templates, 5 procedure templates, 20 medications, 4 appointment types, 2 schedules, 4 unit types, 17 service units, 4 service items |
| Optional | 96 draft Sales Invoices, one per completed visit (`invoices=1`) |

Dates are relative to the anchor date in `data/manifest.json` (120 days of history, 21 days ahead).

## Prerequisites on the site

- ERPNext v16 with at least one Company (any currency; prices are written in OMR values).
- Marley Health v16.6.1 **installed** — its install seeds what the dataset relies on:
  23 medical departments, *Laboratory*/*Drug* item groups, dosage forms, prescription dosages and
  durations, Lab Test UOMs, the medication-class tree with ingredient leaves, code systems.
- A *Standard Selling* price list (or a default selling price list in Selling Settings).
- No custom apps are required. The loader adjusts a few Healthcare Settings (listed below) and
  restores them on purge.

## Option A — bench loader (recommended, loads everything)

```bash
cd ~/frappe-bench
bench get-app /path/to/marley_demo_data        # or unzip into apps/ and: bench pip install -e apps/marley_demo_data
bench --site <site> install-app marley_demo_data   # required: Frappe v16 only executes methods of installed apps
bench --site <site> execute marley_demo_data.loader.load
bench --site <site> execute marley_demo_data.loader.load --kwargs "{'company': 'My Clinic LLC', 'invoices': 1}"
bench --site <site> execute marley_demo_data.loader.verify
bench --site <site> execute marley_demo_data.loader.purge --kwargs "{'confirm': 1}"
bench --site <site> uninstall-app marley_demo_data  # afterwards, if you like
```

The app has no DocTypes, so installing it changes nothing on the site. Options: `company` (default:
the global default company), `invoices` (draft Sales Invoices), `submit`, `set_settings`.

- **Idempotent**: re-running skips what exists (patients by `DEMO-xxxx` UID, practitioners by name, masters by key).
- **Company-aware**: service-unit names are re-suffixed for the target company's abbreviation.
- **Real controllers**: encounters are submitted through Marley, so Service/Medication Requests, medical
  records, bed occupancy and calendar events are genuine.
- **Purge**: removes everything it created (plus any patient with a `DEMO-` UID), restores Healthcare
  Settings, and keeps its state file if anything could not be deleted so it can be re-run. Masters
  that already existed on your site are never touched — that includes masters you imported yourself
  through Data Import (Option B); remove those from their list views if needed.

Healthcare Settings set for the demo: Patient Name By = *Patient Name*, Link Customer to Patient = on,
payment popup / registration fee / SMS / nursing-checklist validation / lab approval = off.

## Option B — Data Import UI (files 00–19: masters, practitioners, patients)

1. Set **Healthcare Settings → Patient Name By = Patient Name** (patient IDs then equal the names later files use).
2. If your company abbreviation isn't `MHD`, regenerate:
   `python3 tools/generate_dataset.py --company "<Company>" --abbr <ABBR> --anchor <YYYY-MM-DD>`
3. Import **00 → 18** with *Insert New Records*, then **19** with *Update Existing Records*.
   A "Territory Oman already exists" row error is harmless if your site already has it.
4. Run the loader for **20–25**. It recognises everything imported in steps 1–3 and only adds the transactions.

Why 20–25 need the loader: Marley v16.6.1 names practitioners with a naming series (`HLC-PRAC-2026-00001`),
appointments/encounters likewise, so those rows can only be linked once the IDs exist; past appointment
statuses, lab results and bed admissions also have to go through Marley's own functions.

## Import order and dependencies

| # | File | DocType | Depends on |
|---|---|---|---|
| 00 | uom | UOM | — |
| 01 | customer_group | Customer Group | — |
| 02 | territory | Territory | — |
| 03 | item_group | Item Group | — |
| 04 | item_services | Item | 00, 03 |
| 05 | medical_department | Medical Department | Marley seed |
| 06 | dosage_form | Dosage Form | — |
| 07 | lab_test_uom | Lab Test UOM | — |
| 08 | complaint | Complaint | — |
| 09 | diagnosis | Diagnosis | — |
| 10 | appointment_type | Appointment Type | — |
| 11 | practitioner_schedule | Practitioner Schedule | — |
| 12 | service_unit_type | Healthcare Service Unit Type | 03 |
| 13 | healthcare_service_unit | Healthcare Service Unit (tree) | 12, Company root |
| 14 | lab_test_template | Lab Test Template (+Item) | 07, Marley seed |
| 15 | clinical_procedure_template | Clinical Procedure Template (+Item) | 03, 05 |
| 16 | medication | Medication (+Item, Item Price) | 00, 06, Marley seed |
| 17 | healthcare_practitioner | Healthcare Practitioner | 04, 05, 11, 13 |
| 18 | patient | Patient (+Customer, Contact) | 01, 02 |
| 19 | patient_relation_update | Patient (update) | 18 |
| 20 | patient_appointment | Patient Appointment (loader) | 10, 13, 17, 18 |
| 21 | patient_encounter | Patient Encounter (loader, submitted) | 08, 09, 14, 15, 16, 20 |
| 22 | vital_signs | Vital Signs (loader, submitted) | 20, 21 |
| 23 | lab_test_results | Lab Test (loader) | 21 |
| 24 | clinical_procedure | Clinical Procedure (loader) | 21 |
| 25 | inpatient_record | Inpatient Record (loader) | 13, 21 |

## Tested

Loaded end-to-end on a fresh Frappe 16.51 / ERPNext 16.50 / Marley 16.6.1 site (company *Kreatao Clinic LLC*,
abbr KC, OMR): 0 failures, ~45 s; re-run skipped everything; purge returned item, customer, contact,
event and transaction counts to their pre-load values. Files 00–19 were also imported through Frappe's
own Data Import engine with 0 failures, followed by the loader for 20–25.

## Regenerating

`tools/generate_dataset.py` is deterministic (fixed seed). Change `--anchor` to move the timeline,
`--company/--abbr` to retarget, or edit the profile tables to change the clinical mix.
