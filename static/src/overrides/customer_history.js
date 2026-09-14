/** @odoo-module **/

import { PosRetailCustomerProfile } from "@pos_retail/overrides/customer_profile";

// Re-export PosRetailCustomerProfile as PosRetailCustomerHistory so all existing
// imports resolve to the unified single popup without duplicate components or models.
export class PosRetailCustomerHistory extends PosRetailCustomerProfile {}

