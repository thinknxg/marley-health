import frappe
from marley_demo_data.patches import load_demo_data_v2


def execute():
    load_demo_data_v2.execute()
    frappe.db.commit()
