import frappe


def execute():
    from marley_demo_data import loader

    try:
        loader.load()
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        frappe.log_error(title="Marley demo data load failed")
