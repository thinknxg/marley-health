import frappe


def execute():
    from marley_demo_data import loader

    try:
        result = loader.load()
        frappe.db.commit()
        frappe.log_error(
            title="Marley demo load result",
            message=f"load() returned: {result!r}\n\nverify() returned: {loader.verify()!r}",
        )
    except Exception:
        frappe.db.rollback()
        frappe.log_error(title="Marley demo data load failed (retry)")
