"""
Marley Health demo-data loader for Frappe v16 / ERPNext v16 / Marley Health v16.6.1.

    bench --site <site> execute marley_demo_data.loader.load
    bench --site <site> execute marley_demo_data.loader.load --kwargs "{'company': 'My Clinic LLC'}"
    bench --site <site> execute marley_demo_data.loader.verify
    bench --site <site> execute marley_demo_data.loader.purge --kwargs "{'confirm': 1}"

The loader reads the CSVs in ../data in manifest order. Masters are inserted only when
missing (idempotent). Transactions are created through the same controllers the UI uses,
so Service Requests, Medication Requests, Patient Medical Records, bed
occupancy and calendar Events are produced by Marley itself.

Everything it creates is recorded in private/files/marley_demo_state.json, which
`purge` uses to remove the demo cleanly and restore Healthcare Settings.
"""

import csv
import json
import os
from collections import OrderedDict, defaultdict

import frappe
from frappe.utils import add_days, cint, flt, get_datetime, getdate

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
STATE_FILE = "marley_demo_state.json"

SETTINGS_FOR_DEMO = {
    "patient_name_by": "Patient Name",
    "link_customer_to_patient": 1,
    "show_payment_popup": 0,
    "collect_registration_fee": 0,
    "send_registration_msg": 0,
    "send_appointment_confirmation": 0,
    "send_appointment_reminder": 0,
    "validate_nursing_checklists": 0,
    "create_sample_collection_for_lab_test": 0,
    "lab_test_approval_required": 0,
}


# ------------------------------------------------------------------------------------
# state / logging
# ------------------------------------------------------------------------------------

def _state_path():
    return frappe.get_site_path("private", "files", STATE_FILE)


def _load_state():
    p = _state_path()
    if os.path.exists(p):
        with open(p) as fh:
            return json.load(fh)
    return {"created": [], "settings_before": None, "maps": {}}


def _save_state(state):
    with open(_state_path(), "w") as fh:
        json.dump(state, fh, indent=1, default=str)


class Log:
    def __init__(self):
        self.counts = defaultdict(lambda: [0, 0, 0])  # created, skipped, failed
        self.errors = []

    def ok(self, dt):
        self.counts[dt][0] += 1

    def skip(self, dt):
        self.counts[dt][1] += 1

    def fail(self, dt, ref, exc):
        self.counts[dt][2] += 1
        msg = frappe.utils.strip_html(str(exc))[:300]
        self.errors.append(f"{dt} [{ref}]: {msg}")

    def report(self):
        print("\n{:<32}{:>9}{:>9}{:>8}".format("DocType", "created", "skipped", "failed"))
        for dt, (c, s, f) in self.counts.items():
            print(f"{dt:<32}{c:>9}{s:>9}{f:>8}")
        if self.errors:
            print(f"\n{len(self.errors)} error(s):")
            for e in self.errors[:60]:
                print("  -", e)


# ------------------------------------------------------------------------------------
# CSV parsing (Frappe Data Import layout: child rows continue the previous parent)
# ------------------------------------------------------------------------------------

def read_docs(fname):
    with open(os.path.join(DATA_DIR, fname), newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    header, rows = rows[0], rows[1:]
    parent_idx = [i for i, h in enumerate(header) if "." not in h]
    tables = OrderedDict()
    for i, h in enumerate(header):
        if "." in h:
            t, f = h.split(".", 1)
            tables.setdefault(t, []).append((i, f))

    docs = []
    for r in rows:
        if any(r[i] for i in parent_idx):
            doc = {header[i]: r[i] for i in parent_idx if r[i] != ""}
            docs.append(doc)
        doc = docs[-1]
        for t, cols in tables.items():
            if any(r[i] for i, _ in cols):
                doc.setdefault(t, []).append({f: r[i] for i, f in cols if r[i] != ""})
    return docs


def read_rows(fname):
    with open(os.path.join(DATA_DIR, fname), newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ------------------------------------------------------------------------------------
# main
# ------------------------------------------------------------------------------------

def load(company=None, submit=1, invoices=0, set_settings=1):
    """Load the full demo dataset. Safe to re-run: existing records are skipped."""
    frappe.flags.mute_emails = True
    frappe.flags.in_import = False  # run real controllers
    manifest = json.load(open(os.path.join(DATA_DIR, "manifest.json")))

    company = company or frappe.defaults.get_global_default("company") or manifest["company"]
    if not frappe.db.exists("Company", company):
        frappe.throw(f"Company '{company}' not found. Pass --kwargs \"{{'company': '<name>'}}\"")
    abbr = frappe.get_cached_value("Company", company, "abbr")
    src_abbr = manifest["abbr"]
    print(f"Loading Marley demo into company '{company}' (abbr {abbr}), anchor {manifest['anchor']}")

    ctx = frappe._dict(company=company, abbr=abbr, src_abbr=src_abbr, src_company=manifest["company"],
                       state=_load_state(), log=Log(), submit=cint(submit))
    ctx.price_list = (
        "Standard Selling" if frappe.db.exists("Price List", "Standard Selling")
        else frappe.db.get_single_value("Selling Settings", "selling_price_list")
    )

    _preflight(ctx)
    if cint(set_settings):
        _apply_settings(ctx)

    steps = [
        ("00_uom.csv", _masters, dict(key="uom_name")),
        ("01_customer_group.csv", _masters, dict(key="customer_group_name")),
        ("02_territory.csv", _masters, dict(key="territory_name")),
        ("03_item_group.csv", _masters, dict(key="item_group_name")),
        ("04_item_services.csv", _masters, dict(key="item_code")),
        ("05_medical_department.csv", _masters, dict(key="department")),
        ("06_dosage_form.csv", _masters, dict(key="dosage_form")),
        ("07_lab_test_uom.csv", _masters, dict(key="lab_test_uom")),
        ("08_complaint.csv", _masters, dict(key="complaints")),
        ("09_diagnosis.csv", _masters, dict(key="diagnosis")),
        ("10_appointment_type.csv", _masters, dict(key="appointment_type")),
        ("11_practitioner_schedule.csv", _masters, dict(key="schedule_name")),
        ("12_service_unit_type.csv", _masters, dict(key="service_unit_type")),
        ("13_healthcare_service_unit.csv", _service_units, {}),
        ("14_lab_test_template.csv", _masters, dict(key="lab_test_name")),
        ("15_clinical_procedure_template.csv", _masters, dict(key="template")),
        ("16_medication.csv", _medications, {}),
        ("17_healthcare_practitioner.csv", _practitioners, {}),
        ("18_patient.csv", _patients, {}),
        ("19_patient_relation_update.csv", _relations, {}),
        ("20_patient_appointment.csv", _appointments, {}),
        ("21_patient_encounter.csv", _encounters, {}),
        ("22_vital_signs.csv", _vitals, {}),
        ("23_lab_test_results.csv", _lab_tests, {}),
        ("24_clinical_procedure.csv", _procedures, {}),
        ("25_inpatient_record.csv", _inpatients, {}),
    ]
    try:
        for fname, fn, kw in steps:
            doctype = next(f["doctype"] for f in manifest["files"] if f["file"] == fname)
            print(f"-> {fname}")
            fn(ctx, fname, doctype, **kw)
            frappe.db.commit()
            _save_state(ctx.state)

        if cint(invoices):
            print("-> draft Sales Invoices for closed appointments")
            _invoices(ctx)
            frappe.db.commit()
    finally:
        _save_state(ctx.state)
        ctx.log.report()
    print(f"\nState saved to {_state_path()}")


# ------------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------------

def _track(ctx, doctype, name):
    ctx.state["created"].append([doctype, name])


def _su(ctx, name):
    """Re-suffix service-unit names for the target company abbreviation."""
    if name and ctx.abbr != ctx.src_abbr and name.endswith(f" - {ctx.src_abbr}"):
        return name[: -len(ctx.src_abbr)] + ctx.abbr
    return name


def _fix_company(ctx, doc):
    if doc.get("company") == ctx.src_company:
        doc["company"] = ctx.company
    return doc


AUTO_ITEM_DOCTYPES = {"Lab Test Template", "Clinical Procedure Template", "Healthcare Service Unit Type"}
NUMERIC_INT = {"Int", "Check"}
NUMERIC_FLOAT = {"Float", "Currency", "Percent"}


def _coerce(doctype, data):
    """CSV values are strings; cast them the way Data Import does ("0" must not be truthy)."""
    meta = frappe.get_meta(doctype)
    out = {}
    for k, v in data.items():
        df = meta.get_field(k)
        if df and df.fieldtype in ("Table", "Table MultiSelect") and isinstance(v, list):
            out[k] = [_coerce(df.options, row) for row in v]
        elif df and df.fieldtype in NUMERIC_INT:
            out[k] = cint(v)
        elif df and df.fieldtype in NUMERIC_FLOAT:
            out[k] = flt(v)
        elif v == "":
            out[k] = None
        else:
            out[k] = v
    return out


def _insert(ctx, doctype, data, ref):
    try:
        doc = frappe.get_doc({"doctype": doctype, **_coerce(doctype, data)})
        doc.insert(ignore_permissions=True)
        frappe.db.commit()  # one record per transaction: a later failure rolls back only itself
        _track(ctx, doctype, doc.name)
        if doctype in AUTO_ITEM_DOCTYPES:  # templates that create their own billing Item
            item = frappe.db.get_value(doctype, doc.name, "item")
            if item:
                _track(ctx, "Item", item)
        ctx.log.ok(doctype)
        return doc
    except Exception as e:
        frappe.db.rollback()
        ctx.log.fail(doctype, ref, e)
        return None


def _preflight(ctx):
    missing = []
    for dt, name in [("Item Group", "Laboratory"), ("Item Group", "Drug"), ("Medical Department", "Cardiology"),
                     ("Prescription Dosage", "BID"), ("Prescription Duration", "1 Month"), ("Dosage Form", "Tablet"),
                     ("Medication Class", "Metformin"), ("UOM", "Nos"), ("Gender", "Male"), ("Gender", "Female"),
                     ("Customer Group", "All Customer Groups"), ("Territory", "All Territories")]:
        if not frappe.db.exists(dt, name):
            missing.append(f"{dt}: {name}")
    if not ctx.price_list:
        missing.append("Price List: 'Standard Selling' or Selling Settings default")
    root = f"All Healthcare Service Units - {ctx.abbr}"
    if not frappe.db.exists("Healthcare Service Unit", root):
        from healthcare.healthcare.utils import create_healthcare_service_unit_tree_root
        create_healthcare_service_unit_tree_root(frappe.get_doc("Company", ctx.company))
        print(f"   created missing service-unit root {root}")
    if missing:
        frappe.throw("Marley seed data missing (is healthcare installed on this site?): " + "; ".join(missing))


def _apply_settings(ctx):
    hs = frappe.get_single("Healthcare Settings")
    if ctx.state.get("settings_before") is None:
        ctx.state["settings_before"] = {k: hs.get(k) for k in SETTINGS_FOR_DEMO}
        print(f"   saved original settings: {ctx.state['settings_before']}")
    for k, v in SETTINGS_FOR_DEMO.items():
        hs.set(k, v)
    hs.flags.ignore_mandatory = True
    hs.save(ignore_permissions=True)
    frappe.db.commit()
    print("   Healthcare Settings adjusted for the demo (restored by purge)")


# ------------------------------------------------------------------------------------
# step handlers
# ------------------------------------------------------------------------------------

def _masters(ctx, fname, doctype, key):
    for d in read_docs(fname):
        d = _fix_company(ctx, d)
        if doctype == "Medication":
            d["price_list"] = ctx.price_list
        if frappe.db.exists(doctype, d[key]) or frappe.db.exists(doctype, {key: d[key]}):
            ctx.log.skip(doctype)
            continue
        if doctype == "Item" and d.get("standard_rate"):
            d["standard_rate"] = flt(d["standard_rate"])
        if doctype == "Clinical Procedure Template" and frappe.db.exists("Item", d.get("item_code")):
            d["link_existing_item"] = 1
            d["item"] = d["item_code"]
        _insert(ctx, doctype, d, d[key])


def _service_units(ctx, fname, doctype):
    for d in read_docs(fname):
        d["company"] = ctx.company
        name = f"{d['healthcare_service_unit_name']} - {ctx.abbr}"
        parent = d.get("parent_healthcare_service_unit", "")
        d["parent_healthcare_service_unit"] = _su(ctx, parent) if parent.endswith(f" - {ctx.src_abbr}") \
            else f"{parent} - {ctx.abbr}"
        if frappe.db.exists(doctype, name):
            ctx.log.skip(doctype)
            continue
        _insert(ctx, doctype, d, name)


def _medications(ctx, fname, doctype):
    for d in read_docs(fname):
        d["price_list"] = ctx.price_list
        item_code = d["linked_items"][0]["item_code"]
        if frappe.db.exists("Medication Linked Item", {"item": item_code}) or \
                frappe.db.exists("Medication Linked Item", {"item_code": item_code}):
            ctx.log.skip(doctype)
            continue
        if frappe.db.exists("Item", item_code):
            ctx.log.fail(doctype, d["generic_name"], f"Item {item_code} already exists but is not linked to a Medication")
            continue
        for li in d["linked_items"]:
            li["rate"] = flt(li["rate"])
        d["strength"] = flt(d["strength"])
        doc = _insert(ctx, doctype, d, d["generic_name"])
        if doc:
            _track(ctx, "Item", item_code)


def _practitioners(ctx, fname, doctype):
    # Marley v16.6.1 names practitioners by naming series (HLC-PRAC-.YYYY.-), so later
    # files reference them by full name and the loader maps that to the generated ID.
    pr = ctx.state["maps"].setdefault("practitioner", {})
    for d in read_docs(fname):
        full = f"{d['first_name']} {d['last_name']}"
        existing = frappe.db.get_value(doctype, {"practitioner_name": full})
        if existing:
            pr[full] = existing
            ctx.log.skip(doctype)
            continue
        for row in d.get("practitioner_schedules", []):
            row["service_unit"] = _su(ctx, row.get("service_unit"))
        doc = _insert(ctx, doctype, d, full)
        if doc:
            pr[full] = doc.name


def _pr(ctx, full):
    return ctx.state["maps"].get("practitioner", {}).get(full, full)


def _patients(ctx, fname, doctype):
    pmap = ctx.state["maps"].setdefault("patient", {})
    for d in read_docs(fname):
        full = f"{d['first_name']} {d['last_name']}"
        existing = frappe.db.get_value("Patient", {"uid": d["uid"]})
        if existing:
            pmap[full] = existing
            ctx.log.skip(doctype)
            continue
        d["invite_user"] = 0
        doc = _insert(ctx, doctype, d, d["uid"])
        if doc:
            pmap[full] = doc.name
            doc.reload()
            if doc.customer:
                _track(ctx, "Customer", doc.customer)


def _p(ctx, full):
    return ctx.state["maps"]["patient"].get(full, full)


def _relations(ctx, fname, doctype):
    for d in read_docs(fname):
        name = _p(ctx, d["name"])
        try:
            doc = frappe.get_doc("Patient", name)
            existing = {r.patient for r in doc.patient_relation}
            added = 0
            for r in d.get("patient_relation", []):
                rp = _p(ctx, r["patient"])
                if rp not in existing:
                    doc.append("patient_relation", {"patient": rp, "relation": r["relation"]})
                    added += 1
            if added:
                doc.save(ignore_permissions=True)
                frappe.db.commit()
                ctx.log.ok("Patient Relation")
            else:
                ctx.log.skip("Patient Relation")
        except Exception as e:
            frappe.db.rollback()
            ctx.log.fail("Patient Relation", d["name"], e)


def _appointments(ctx, fname, doctype):
    amap = ctx.state["maps"].setdefault("appointment", {})
    for r in read_rows(fname):
        ref = r.pop("_ref")
        if ref in amap and frappe.db.exists(doctype, amap[ref]):
            ctx.log.skip(doctype)
            continue
        r = _fix_company(ctx, r)
        r["patient"] = _p(ctx, r["patient"])
        r["practitioner"] = _pr(ctx, r["practitioner"])
        r["service_unit"] = _su(ctx, r["service_unit"])
        r["duration"] = cint(r["duration"])
        doc = _insert(ctx, doctype, r, ref)
        if doc:
            amap[ref] = doc.name
            if doc.get("event"):
                _track(ctx, "Event", doc.event)
            # Status-dependent hooks may have moved status; pin the intended one
            if doc.status != r["status"]:
                doc.db_set("status", r["status"], update_modified=False)
                frappe.db.commit()


def _encounters(ctx, fname, doctype):
    emap = ctx.state["maps"].setdefault("encounter", {})
    amap = ctx.state["maps"].get("appointment", {})
    for d in read_docs(fname):
        ref = d.pop("_ref")
        appt_ref = d.pop("_appointment_ref", None)
        if ref in emap and frappe.db.exists(doctype, emap[ref]):
            ctx.log.skip(doctype)
            continue
        d = _fix_company(ctx, d)
        d["patient"] = _p(ctx, d["patient"])
        d["practitioner"] = _pr(ctx, d["practitioner"])
        if appt_ref:
            if appt_ref not in amap:
                ctx.log.fail(doctype, ref, f"appointment {appt_ref} was not created")
                continue
            d["appointment"] = amap[appt_ref]
        for row in d.get("procedure_prescription", []):
            row["no_of_sessions"] = cint(row.get("no_of_sessions") or 1)
        doc = _insert(ctx, doctype, d, ref)
        if not doc:
            continue
        emap[ref] = doc.name
        if ctx.submit:
            try:
                doc.submit()
                frappe.db.commit()
                for t in ("Service Request", "Medication Request"):
                    for n in frappe.get_all(t, {"order_group": doc.name}, pluck="name"):
                        _track(ctx, t, n)
            except Exception as e:
                frappe.db.rollback()
                ctx.log.fail(doctype + " (submit)", ref, e)


def _vitals(ctx, fname, doctype):
    emap = ctx.state["maps"].get("encounter", {})
    amap = ctx.state["maps"].get("appointment", {})
    done = ctx.state["maps"].setdefault("vitals", {})
    for r in read_rows(fname):
        eref, aref = r.pop("_encounter_ref"), r.pop("_appointment_ref")
        if eref in done:
            ctx.log.skip(doctype)
            continue
        r = _fix_company(ctx, r)
        r["patient"] = _p(ctx, r["patient"])
        if eref not in emap:
            ctx.log.fail(doctype, eref, "encounter not created")
            continue
        r["encounter"] = emap.get(eref)
        r["appointment"] = amap.get(aref) if aref else None
        h, w = flt(r["height"]), flt(r["weight"])
        r["height"], r["weight"] = h, w
        if h:
            r["bmi"] = round(w / (h * h), 2)
        r["bp"] = f"{r['bp_systolic']}/{r['bp_diastolic']} mmHg"
        doc = _insert(ctx, doctype, r, eref)
        if doc:
            done[eref] = doc.name
            if ctx.submit:
                try:
                    doc.submit()
                    frappe.db.commit()
                except Exception as e:
                    frappe.db.rollback()
                    ctx.log.fail(doctype + " (submit)", eref, e)


def _service_request_for(encounter, table, field, value):
    for row in encounter.get(table):
        if row.get(field) == value and row.get("service_request"):
            return row.service_request
    return None


def _lab_tests(ctx, fname, doctype):
    emap = ctx.state["maps"].get("encounter", {})
    done = ctx.state["maps"].setdefault("lab_test", {})
    grouped = OrderedDict()
    for r in read_rows(fname):
        grouped.setdefault((r["_encounter_ref"], r["template"]), []).append(r)

    for (eref, template), results in grouped.items():
        key = f"{eref}|{template}"
        if key in done:
            ctx.log.skip(doctype)
            continue
        if eref not in emap:
            ctx.log.fail(doctype, key, "encounter not created")
            continue
        enc = frappe.get_doc("Patient Encounter", emap[eref])
        sr = _service_request_for(enc, "lab_test_prescription", "lab_test_code", template)
        data = dict(template=template, patient=enc.patient, patient_sex=frappe.db.get_value("Patient", enc.patient, "sex"),
                    practitioner=enc.practitioner, requesting_department=enc.medical_department,
                    company=enc.company, service_request=sr, date=enc.encounter_date, time=enc.encounter_time)
        doc = _insert(ctx, doctype, data, key)
        if not doc:
            continue
        done[key] = doc.name
        try:
            doc.reload()
            values = {x["lab_test_name"]: x["result_value"] for x in results}
            for item in doc.normal_test_items:
                name = item.lab_test_name or item.lab_test_event
                if name in values:
                    item.result_value = str(values[name])
            doc.save(ignore_permissions=True)
            if results[0]["status"] == "Completed" and ctx.submit:
                doc.submit()
                doc.db_set({"result_date": results[0]["result_date"],
                            "submitted_date": get_datetime(f"{results[0]['result_date']} 11:00:00")},
                           update_modified=False)
            else:
                doc.db_set("result_date", None, update_modified=False)
            frappe.db.commit()
        except Exception as e:
            frappe.db.rollback()
            ctx.log.fail(doctype + " (results)", key, e)


def _procedures(ctx, fname, doctype):
    emap = ctx.state["maps"].get("encounter", {})
    done = ctx.state["maps"].setdefault("procedure", {})
    for r in read_rows(fname):
        key = f"{r['_encounter_ref']}|{r['procedure_template']}"
        if key in done:
            ctx.log.skip(doctype)
            continue
        if r["_encounter_ref"] not in emap:
            ctx.log.fail(doctype, key, "encounter not created")
            continue
        enc = frappe.get_doc("Patient Encounter", emap[r["_encounter_ref"]])
        sr = _service_request_for(enc, "procedure_prescription", "procedure", r["procedure_template"])
        data = dict(patient=enc.patient, procedure_template=r["procedure_template"], practitioner=enc.practitioner,
                    medical_department=enc.medical_department, service_request=sr, company=enc.company,
                    start_date=r["start_date"], start_time=r["start_time"])
        doc = _insert(ctx, doctype, data, key)
        if not doc:
            continue
        done[key] = doc.name
        if ctx.submit:
            try:
                doc.submit()
                start = get_datetime(f"{r['start_date']} {r['start_time']}")
                doc.db_set({"status": r["status"], "actual_start_datetime": start,
                            "actual_end_datetime": frappe.utils.add_to_date(start, minutes=20)},
                           update_modified=False)
                frappe.db.commit()
            except Exception as e:
                frappe.db.rollback()
                ctx.log.fail(doctype + " (submit)", key, e)


def _inpatients(ctx, fname, doctype):
    from healthcare.healthcare.doctype.inpatient_record.inpatient_record import (
        admit_patient,
        create_inpatient_record,
    )

    emap = ctx.state["maps"].get("encounter", {})
    done = ctx.state["maps"].setdefault("inpatient", {})
    for r in read_rows(fname):
        key = r["_admission_encounter_ref"]
        if key in done:
            ctx.log.skip(doctype)
            continue
        if key not in emap:
            ctx.log.fail(doctype, key, "admission encounter not created")
            continue
        patient = _p(ctx, r["patient"])
        if frappe.db.get_value("Patient", patient, "inpatient_status"):
            ctx.log.skip(doctype)
            continue
        try:
            order = dict(patient=patient, admission_encounter=emap[key], medical_department=r["medical_department"],
                         primary_practitioner=_pr(ctx, r["primary_practitioner"]),
                         admission_practitioner=_pr(ctx, r["admission_practitioner"]),
                         admission_service_unit_type=r["admission_service_unit_type"],
                         expected_length_of_stay=cint(r["expected_length_of_stay"]),
                         admission_instruction=r["admission_instruction"], company=ctx.company)
            ip_name = create_inpatient_record(order)
            _track(ctx, doctype, ip_name)
            frappe.db.set_value("Patient", patient, {"inpatient_status": "Admission Scheduled", "inpatient_record": ip_name})
            if r["status"] == "Admitted":
                ip = frappe.get_doc(doctype, ip_name)
                check_in = get_datetime(r["_check_in"])
                expected = add_days(check_in, cint(r["expected_length_of_stay"]))
                admit_patient(ip, _su(ctx, r["_bed"]), check_in, expected)
            done[key] = ip_name
            frappe.db.commit()
            ctx.log.ok(doctype)
        except Exception as e:
            frappe.db.rollback()
            ctx.log.fail(doctype, key, e)


def _invoices(ctx):
    from healthcare.healthcare.doctype.healthcare_settings.healthcare_settings import get_receivable_account
    from healthcare.healthcare.doctype.patient_appointment.patient_appointment import get_appointment_item

    done = ctx.state["maps"].setdefault("invoice", {})
    for ref, appt in ctx.state["maps"].get("appointment", {}).items():
        if ref in done:
            continue
        a = frappe.get_doc("Patient Appointment", appt)
        if a.status != "Closed" or a.invoiced:
            continue
        try:
            si = frappe.new_doc("Sales Invoice")
            si.patient = a.patient
            si.customer = frappe.db.get_value("Patient", a.patient, "customer")
            si.appointment = a.name
            si.company = a.company
            si.set_posting_time = 1
            si.posting_date = a.appointment_date
            si.due_date = add_days(a.appointment_date, 30)
            si.debit_to = get_receivable_account(a.company)
            get_appointment_item(a, si.append("items", {}))
            si.set_missing_values(for_validate=True)
            si.insert(ignore_permissions=True)
            frappe.db.commit()
            _track(ctx, "Sales Invoice", si.name)
            done[ref] = si.name
            ctx.log.ok("Sales Invoice (draft)")
        except Exception as e:
            frappe.db.rollback()
            ctx.log.fail("Sales Invoice (draft)", ref, e)


# ------------------------------------------------------------------------------------
# verify / purge
# ------------------------------------------------------------------------------------

def verify():
    """Print counts of demo records by doctype and status."""
    state = _load_state()
    pats = list(state.get("maps", {}).get("patient", {}).values())
    if not pats:
        print("No demo state found.")
        return
    print(f"Demo patients: {len(pats)}")
    for dt, field in [("Patient Appointment", "status"), ("Patient Encounter", "status"), ("Vital Signs", "docstatus"),
                      ("Lab Test", "status"), ("Clinical Procedure", "status"), ("Service Request", "docstatus"),
                      ("Medication Request", "docstatus"), ("Inpatient Record", "status")]:
        from collections import Counter

        counts = Counter(frappe.get_all(dt, filters={"patient": ["in", pats]}, pluck=field))
        print(f"  {dt:<22} " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items(), key=lambda x: str(x[0]))))


PURGE_ORDER = [
    "Sales Invoice", "Clinical Procedure", "Lab Test", "Sample Collection", "Observation", "Vital Signs",
    "Nursing Task", "Inpatient Medication Order", "Inpatient Record", "Medication Request", "Service Request",
    "Therapy Plan", "Patient Encounter", "Fee Validity", "Patient Appointment", "Patient Medical Record",
    "Medication Alert Log",
]


def purge(confirm=0):
    """Remove every demo transaction and the demo masters it created; restore Healthcare Settings."""
    if not cint(confirm):
        print("Dry run. Re-run with --kwargs \"{'confirm': 1}\" to delete.")
    state = _load_state()
    # demo patients are also found by their synthetic UID, so a lost state file still purges them
    pats = sorted(set(state.get("maps", {}).get("patient", {}).values())
                  | set(frappe.get_all("Patient", {"uid": ["like", "DEMO-%"]}, pluck="name")))
    failures = []
    frappe.flags.ignore_links = True
    # delete_doc enqueues one delete_dynamic_links job per document; run them inline so a
    # purge of ~1,500 records cannot overflow the queue (Frappe caps queued jobs at 500).
    _in_test = frappe.in_test
    frappe.in_test = True

    def kill(dt, name):
        if not frappe.db.exists(dt, name):
            return
        if not cint(confirm):
            print(f"  would delete {dt} {name}")
            return
        try:
            doc = frappe.get_doc(dt, name)
            if doc.docstatus == 1:
                doc.flags.ignore_links = True
                doc.cancel()
            frappe.delete_doc(dt, name, force=True, ignore_permissions=True, ignore_missing=True)
        except Exception as e:
            frappe.db.rollback()
            failures.append(f"{dt} {name}")
            print(f"  ! {dt} {name}: {str(e)[:160]}")

    # 1. everything hanging off demo patients, in dependency order
    for dt in PURGE_ORDER:
        if not frappe.db.exists("DocType", dt) or not pats:
            continue
        field = "patient" if frappe.get_meta(dt).has_field("patient") else None
        if not field:
            continue
        for n in frappe.get_all(dt, {field: ["in", pats]}, pluck="name", order_by="creation desc"):
            kill(dt, n)
        frappe.db.commit()

    # contacts / addresses Marley created for demo patients, customers and practitioners
    linked = pats + [n for d, n in state.get("created", []) if d in ("Customer", "Healthcare Practitioner")]
    if linked:
        for parenttype in ("Contact", "Address"):
            for n in frappe.get_all("Dynamic Link", {"parenttype": parenttype, "link_name": ["in", linked],
                                                     "link_doctype": ["in", ["Patient", "Customer", "Healthcare Practitioner"]]},
                                    pluck="parent", distinct=True):
                kill(parenttype, n)
        frappe.db.commit()

    # free beds
    for n in frappe.get_all("Healthcare Service Unit", {"name": ["like", "Ward A Bed %"]}, pluck="name"):
        if cint(confirm):
            frappe.db.set_value("Healthcare Service Unit", n, "occupancy_status", "Vacant")

    # 2. everything recorded in state, newest first (patients, masters, items...)
    for dt, name in reversed(state.get("created", [])):
        if dt in PURGE_ORDER:
            continue
        kill(dt, name)
    frappe.db.commit()

    # patients and their customers (also when untracked)
    for p in pats:
        cust = frappe.db.get_value("Patient", p, "customer")
        kill("Patient", p)
        if cust and not frappe.db.exists("Patient", {"customer": cust}):
            kill("Customer", cust)
    frappe.db.commit()

    if failures:
        print(f"{len(failures)} record(s) could not be deleted; state file kept so purge can be re-run.")
    elif cint(confirm):
        before = state.get("settings_before")
        if before:
            hs = frappe.get_single("Healthcare Settings")
            for k, v in before.items():
                hs.set(k, v)
            hs.flags.ignore_mandatory = True
            hs.save(ignore_permissions=True)
        if os.path.exists(_state_path()):
            os.remove(_state_path())
        frappe.db.commit()
        print("Demo data removed and Healthcare Settings restored.")
    frappe.in_test = _in_test
