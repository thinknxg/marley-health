# Marley Demo Data (v16.6.1)

Synthetic, 50-patient demo dataset for **Frappe v16 + ERPNext v16 + Marley Health (healthcare) v16.6.1**,
shipped as dependency-ordered CSV import files plus a bench loader that creates the clinical and
insurance transactions through Marley's own controllers.

All people, phone numbers, IDs (`DEMO-0001`…), e-mails (`@example.com`) and the three insurance payors
are fictitious. Context: Oman clinic — OMR prices, Sun–Thu working week (Fri–Sat weekend), +968 numbers.

## What's in it

### Clinical

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

### Insurance

| DocType | Records |
|---|---|
| Insurance Payor | 3 — *Al Wadi Health Insurance* (30-day credit), *Muscat Shield Assurance* (45), *Gulf Crescent TPA* (60); each gets its Customer, receivable and rejected-claims accounts |
| Insurance Payor Contract | 6 (submitted) — previous + current contract year per payor, with Jan / Apr / Jul renewal months |
| Insurance Payor Eligibility Plan | 5 — Al Wadi Gold / Silver, Muscat Shield Corporate / Essential, Gulf Crescent Standard |
| Item Insurance Eligibility | 87 — consultations as *Item* rules, labs / procedures / ward bed as *Service* rules, chronic drugs as *Item* rules; 70–100 % coverage, 0–10 % discounts, *Manual* (pre-authorisation) rules on Silver procedures and Essential procedures / HbA1c / TSH |
| Price List + Item Price | 2 negotiated tariffs (34 prices): *Al Wadi Tariff* on the contract, *Gulf Crescent Tariff* on the plan — both price-resolution levels Marley supports |
| Patient Insurance Policy | 33 (submitted) — expatriate employees and Omani members, dependants carry the principal's number with `-01`, `-02` |
| Patient Insurance Coverage | 155 created by Marley from appointments and orders: 125 invoiced, 24 approved and not yet billed (upcoming / today / inpatient), 4 cancelled (no-shows, cancellations), 1 pre-authorisation rejected, 1 awaiting the payor |
| Sales Invoice | 59 submitted insured invoices built with *Get Items from Healthcare Services*; Marley posts 125 payor-transfer Journal Entries; 47 patient co-pays received |
| Insurance Claim | 52 — one per patient-policy per service month: 40 *Completed* (paid, some lines rejected), 9 *Submitted* (6 approved awaiting remittance, 3 awaiting adjudication), 2 *Error* (fully rejected), 1 *Draft* |
| Insurance Claim Coverage | 123 lines, 7 rejected with a reason (payor adjudication) |
| Payment Entry | 40 payor remittances (Wire Transfer, with reference numbers) |

Money trail at load (OMR): billed 1,256.522 → payor share 1,050.470 (transferred by Journal Entry) +
patient share 206.052 (187.360 collected); claimed 1,027.790, paid 780.270, rejected 88.510. It ties out:
the insurance receivable balance (270.200) equals payor share minus remittances.

The optional `invoices=1` adds 36 draft Sales Invoices for the uninsured completed visits.
Dates are relative to the anchor date in `data/manifest.json` (120 days of history, 21 days ahead).

## Prerequisites on the site

- ERPNext v16 with at least one Company and a Fiscal Year covering the last 4 months.
- Marley Health v16.6.1 **installed** — its install seeds what the dataset relies on:
  23 medical departments, *Laboratory*/*Drug* item groups, dosage forms, prescription dosages and
  durations, Lab Test UOMs, the medication-class tree with ingredient leaves, code systems.
- A *Standard Selling* price list (or a default selling price list in Selling Settings).
- No custom apps are required. The loader adjusts a few Healthcare Settings (listed below) and
  restores them on purge.
- For insurance billing, the loader creates what it needs if missing: the two insurance ledgers (under
  *Accounts Receivable* and *Indirect Expenses*), and — only if the company has no bank ledger — an
  *Insurance Remittance Bank* ledger set on the *Wire Transfer* mode of payment. Purge removes them.

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

The app has no DocTypes, so installing it changes nothing on the site. Options:

| Option | Default | Effect |
|---|---|---|
| `company` | global default | Target company |
| `insurance` | 1 | 0 = clinical data only (no payors, policies, coverages) |
| `insurance_billing` | 1 | 0 = stop at coverages: no invoices, journal entries, claims or payments are posted |
| `invoices` | 0 | 1 = also draft Sales Invoices for uninsured visits |
| `submit`, `set_settings` | 1 | Submit documents / adjust Healthcare Settings |

- **Idempotent**: re-running skips what exists (patients by `DEMO-xxxx` UID, policies by number, masters by key).
- **Company-aware**: service-unit and account names follow the target company's abbreviation; price lists use its currency.
- **Real controllers**: coverages come from Marley's own appointment and Service Request hooks, invoices from
  *Get Items from Healthcare Services*, claims from the claim's *Get Coverages*, remittances from its
  *Create Payment Entry*. The loader only backdates coverage posting dates to the date of service.
- **Purge**: cancels and removes everything it created in dependency order (remittances → claims → payor
  journal entries → invoices → coverages → policies → masters), removes the related GL and payment-ledger
  rows, restores Healthcare Settings, and keeps its state file if anything could not be deleted so it can
  be re-run. Masters that already existed on your site are never touched — that includes masters you
  imported yourself through Data Import (Option B). Frappe's own *Deleted Document* audit entries remain.

Healthcare Settings set for the demo: Patient Name By = *Patient Name*, Link Customer to Patient = on,
payment popup / registration fee / SMS / nursing-checklist validation / lab approval = off.

## Option B — Data Import UI (files 00–27: masters, practitioners, patients, insurance setup)

1. Set **Healthcare Settings → Patient Name By = Patient Name** (patient IDs then equal the names later files use).
2. If your company abbreviation isn't `MHD`, regenerate:
   `python3 tools/generate_dataset.py --company "<Company>" --abbr <ABBR> --anchor <YYYY-MM-DD>`
3. Import **00 → 27** in order with *Insert New Records* (**19** with *Update Existing Records*). Tick
   *Submit After Import* for **24** (contracts) and **27** (policies). In **20**, the parent accounts are
   the standard chart names (*Accounts Receivable*, *Indirect Expenses*); adjust them if your chart differs.
   A "Territory Oman already exists" row error is harmless.
4. Run the loader for **28–37**. It recognises everything imported in steps 1–3 and only adds the transactions.

Why 28–37 need the loader: Marley names practitioners, appointments, encounters, coverages and invoices
with naming series, so those rows can only be linked once the IDs exist; coverages, payor journal entries
and claim lines are created by Marley at runtime and have no file of their own.

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
| 20 | account | Account (insurance receivable, rejected claims) | Company chart |
| 21 | price_list | Price List (payor tariffs) | — |
| 22 | item_price | Item Price | 04, 14, 15, 21 |
| 23 | insurance_payor | Insurance Payor (+Customer) | 20 |
| 24 | insurance_payor_contract | Insurance Payor Contract (submit) | 21, 23 |
| 25 | insurance_eligibility_plan | Insurance Payor Eligibility Plan | 21, 23 |
| 26 | item_insurance_eligibility | Item Insurance Eligibility | 04, 12, 14, 15, 16, 25 |
| 27 | patient_insurance_policy | Patient Insurance Policy (submit) | 18, 23, 25 |
| 28 | patient_appointment | Patient Appointment (loader) → coverage | 10, 13, 17, 18, 27 |
| 29 | patient_encounter | Patient Encounter (loader, submitted) → Service Requests → coverages | 08, 09, 14, 15, 16, 27, 28 |
| 30 | vital_signs | Vital Signs (loader, submitted) | 28, 29 |
| 31 | lab_test_results | Lab Test (loader) | 29 |
| 32 | clinical_procedure | Clinical Procedure (loader) | 29 |
| 33 | inpatient_record | Inpatient Record (loader) | 13, 29 |
| 34 | coverage_decisions | Patient Insurance Coverage — pre-authorisation outcomes (loader) | 28, 29 |
| 35 | insured_invoices | Sales Invoice + payor Journal Entry + co-pay Payment Entry (loader) | 28, 29, 34 |
| 36 | insurance_claim | Insurance Claim + adjudication + remittance Payment Entry (loader) | 35, 37 |
| 37 | claim_adjudication | Insurance Claim Coverage — rejected lines (loader, read with 36) | 35 |

Columns starting with `_` are loader references or instructions; Data Import ignores them.

## Marley 16.6.1 issues found while building this (and how the loader handles them)

1. **Rounded totals break insured invoices.** With *Rounded Total* enabled (ERPNext default), a 19.250
   bill rounds to 19.000 outstanding, but Marley transfers each line's full payor share by Journal Entry,
   so submission fails with *"Payment … cannot be greater than Outstanding Amount"*. The loader sets
   *Disable Rounded Total* on insured invoices; for live use, disable it in Global Defaults or per invoice.
2. **Payor share is not rounded to currency precision.** The invoice line keeps 3.562 × 80 % = 2.8496 while the
   Journal Entry posts 2.850; the claim later refuses a 2.850 remittance against a 2.8496 claim line
   (*"Paid Amount cannot be more than Claim Amount"*). It shows up whenever a percentage produces more
   decimals than the currency allows (here, Gulf Crescent's 5 % discount). The loader rounds the share
   for invoices it creates; the fix in Marley belongs in `SalesInvoiceMixin.calculate_patient_insurance_coverage`.
3. **Cancelling a Service Request whose coverage awaits pre-authorisation fails** (Marley tries to cancel
   the draft coverage). Purge detaches pending drafts first.

Also by design in 16.6.1: Marley stamps coverages with the creation date (the loader backdates them to the
date of service), bed coverages are created only at discharge, and Medication Requests do not create coverages.

## Tested

On fresh Frappe 16.51 / ERPNext 16.50 / Marley 16.6.1 sites (company *Kreatao Clinic LLC*, abbr KC, OMR):
full load with insurance 0 failures in ~90 s; re-run skipped everything; `insurance=0` loads the clinical
data without coverages; purge returned all 23 tracked tables (accounts, items, prices, customers, contacts,
events, GL and payment-ledger entries, invoices, journal and payment entries, payors, contracts, plans,
eligibility, policies, coverages, claims, patients) to their pre-load counts. Files 00–27 were also
imported through Frappe's own Data Import engine with 0 failures, followed by the loader for 28–37.

## Regenerating

`tools/generate_dataset.py` is deterministic (fixed seed; insurance uses its own seed, so clinical data is
the same with or without it). Change `--anchor` to move the timeline, `--company/--abbr` to retarget, or
edit the profile, payor, plan and policy tables to change the mix. The loader warns when the anchor is
more than 14 days old — policies must not have expired when they are loaded.
