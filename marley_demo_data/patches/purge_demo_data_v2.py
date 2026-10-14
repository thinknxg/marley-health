import frappe


def execute():
    from marley_demo_data import loader

    try:
        loader.purge(confirm=1)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        frappe.log_error(title="Marley demo purge v2 failed")
