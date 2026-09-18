# -*- coding: utf-8 -*-

import html
import json
import math

from odoo import http
from odoo.http import request

from ..models.thermal_barcode_generator import build_zpl_document, generate_barcode_svg


class PosRetailThermalLabelController(http.Controller):

    @http.route('/pos_retail/print_thermal_labels', type='http', auth='user', website=False)
    def print_thermal_labels(self, wizard_id=None, preset_id=None, product_id=None, qty=1, single=None, test=None, **kwargs):
        """
        Renders pure thermal print output tailored to physical roll dimensions.
        Zero document margins, zero headers/footers, exact millimetre width/height.
        """
        env = request.env
        preset = None

        if preset_id:
            preset = env['pos.retail.thermal.label.preset'].browse(int(preset_id))
        elif wizard_id:
            wizard = env['pos.retail.thermal.label.wizard'].browse(int(wizard_id))
            if wizard.exists():
                preset = wizard.preset_id

        if not preset or not preset.exists():
            preset = env['pos.retail.thermal.label.preset'].search([('is_default', '=', True)], limit=1)
            if not preset:
                preset = env['pos.retail.thermal.label.preset'].search([], limit=1)

        if not preset:
            return request.not_found("No thermal label preset configured.")

        # Build list of label dictionaries
        labels = []
        is_test = bool(test)
        is_single = bool(single)

        if is_test:
            # Generate 2 calibration test labels
            for idx in range(1, 3):
                labels.append({
                    'product_name': f"CALIBRATION TEST LABEL #{idx}",
                    'brand': "THERMAL ROLL TEST",
                    'sku': f"TEST-ROLL-{int(preset.roll_width)}MM",
                    'barcode': "123456789012",
                    'price': 999.0,
                    'uom': "Pcs",
                    'is_test': True,
                })
        elif wizard_id:
            wizard = env['pos.retail.thermal.label.wizard'].browse(int(wizard_id))
            if wizard.exists():
                for line in wizard.line_ids:
                    count = 1 if is_single else max(0, line.quantity)
                    for _ in range(count):
                        labels.append({
                            'product_name': line.product_id.display_name,
                            'brand': line.product_id.product_tmpl_id.pos_retail_brand_id.name if hasattr(line.product_id.product_tmpl_id, 'pos_retail_brand_id') and line.product_id.product_tmpl_id.pos_retail_brand_id else '',
                            'sku': line.default_code or '',
                            'barcode': line.barcode or '',
                            'price': line.price,
                            'uom': line.product_id.uom_id.name or '',
                        })
                        if is_single:
                            break
                    if is_single and labels:
                        break
        elif product_id:
            product = env['product.product'].browse(int(product_id))
            if product.exists():
                count = 1 if is_single else max(1, int(qty or 1))
                for _ in range(count):
                    labels.append({
                        'product_name': product.display_name,
                        'brand': product.product_tmpl_id.pos_retail_brand_id.name if hasattr(product.product_tmpl_id, 'pos_retail_brand_id') and product.product_tmpl_id.pos_retail_brand_id else '',
                        'sku': product.default_code or '',
                        'barcode': product.barcode or '',
                        'price': product.lst_price,
                        'uom': product.uom_id.name or '',
                    })

        if not labels:
            return request.not_found("No label items to print.")

        currency_symbol = env.company.currency_id.symbol or "Rs."
        company_name = env.company.name or ""
        cols = max(1, preset.columns)

        # Build rows of columns
        rows = []
        for i in range(0, len(labels), cols):
            row = labels[i:i + cols]
            rows.append(row)

        # Generate HTML Page
        html_content = self._render_thermal_html(preset, rows, cols, currency_symbol, company_name, labels)
        return request.make_response(html_content, headers=[
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Cache-Control', 'no-cache, no-store, must-revalidate'),
        ])

    def _render_thermal_html(self, preset, rows, cols, currency_symbol, company_name, flat_labels):
        font_size = "11px" if preset.font_size == 'normal' else ("9px" if preset.font_size == 'small' else "13px")
        align = preset.text_align or 'center'

        page_css = f"""
        @page {{
            size: {preset.roll_width}mm {preset.label_height}mm;
            margin: 0mm;
        }}
        @media print {{
            html, body {{
                width: {preset.roll_width}mm;
                margin: 0 !important;
                padding: 0 !important;
                background: #ffffff !important;
            }}
            .no-print {{
                display: none !important;
            }}
            .thermal-row {{
                page-break-inside: avoid;
                page-break-after: always;
                break-after: page;
            }}
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
            margin: 0;
            padding: 0;
            background: #f8fafc;
            color: #000000;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }}
        .no-print-toolbar {{
            background: #1e293b;
            color: #ffffff;
            padding: 10px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: sticky;
            top: 0;
            z-index: 999;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }}
        .no-print-toolbar button {{
            padding: 8px 16px;
            border-radius: 6px;
            border: none;
            font-weight: bold;
            cursor: pointer;
        }}
        .btn-print {{
            background: #10b981;
            color: #ffffff;
        }}
        .btn-close {{
            background: #475569;
            color: #ffffff;
            margin-left: 8px;
        }}
        .print-container {{
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 20px 0;
        }}
        @media print {{
            .print-container {{
                padding: 0 !important;
            }}
        }}
        .thermal-row {{
            width: {preset.roll_width}mm;
            height: {preset.label_height}mm;
            display: flex;
            flex-direction: row;
            gap: {preset.gap_horizontal}mm;
            padding: {preset.margin_top}mm {preset.margin_right}mm {preset.margin_bottom}mm {preset.margin_left}mm;
            box-sizing: border-box;
            background: #ffffff;
            overflow: hidden;
            margin-bottom: {preset.gap_vertical}mm;
        }}
        @media print {{
            .thermal-row {{
                margin-bottom: 0 !important;
            }}
        }}
        .thermal-label {{
            width: {preset.label_width}mm;
            height: 100%;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            text-align: {align};
            font-size: {font_size};
            line-height: 1.15;
            overflow: hidden;
            padding: 1px 2px;
        }}
        .thermal-top-meta {{
            font-size: 8px;
            text-transform: uppercase;
            font-weight: 600;
            color: #333333;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .thermal-product-name {{
            font-weight: bold;
            color: #000000;
            max-height: 2.3em;
            overflow: hidden;
            word-break: break-word;
        }}
        .thermal-barcode-box {{
            display: flex;
            justify-content: center;
            align-items: center;
            margin: 1px 0;
        }}
        .thermal-bottom-row {{
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-top: auto;
        }}
        .thermal-price {{
            font-weight: 900;
            font-size: 1.15em;
        }}
        .thermal-sku {{
            font-size: 8.5px;
            color: #222222;
        }}
        """

        body_parts = [
            f"<!DOCTYPE html><html><head><meta charset='utf-8'/>",
            f"<title>Thermal Labels — {html.escape(preset.name)}</title>",
            f"<style>{page_css}</style>",
            f"</head><body>",
            f"<div class='no-print no-print-toolbar'>",
            f"<div><strong>Thermal Roll:</strong> {html.escape(preset.name)} ({preset.roll_width:.1f}mm × {preset.label_height:.1f}mm)</div>",
            f"<div><button class='btn-print' onclick='window.print()'>🖨️ Print Now</button>",
            f"<button class='btn-close' onclick='window.close()'>Close</button></div>",
            f"</div>",
            f"<div class='print-container'>",
        ]

        for row_items in rows:
            body_parts.append("<div class='thermal-row'>")
            for item in row_items:
                barcode_val = item['barcode'] or (item['sku'] if preset.barcode_fallback == 'sku' else '')
                barcode_svg = ""
                if preset.show_barcode and barcode_val:
                    barcode_svg = generate_barcode_svg(
                        barcode_val,
                        barcode_type=preset.barcode_type,
                        height_mm=preset.barcode_height,
                        show_text=preset.show_barcode_text,
                    )

                body_parts.append("<div class='thermal-label'>")

                # Top row: Company / Brand
                top_items = []
                if preset.show_company_name:
                    top_items.append(html.escape(company_name))
                if preset.show_brand and item.get('brand'):
                    top_items.append(html.escape(item['brand']))
                if top_items:
                    body_parts.append(f"<div class='thermal-top-meta'>{' • '.join(top_items)}</div>")

                # Product Name
                if preset.show_product_name:
                    body_parts.append(f"<div class='thermal-product-name'>{html.escape(item['product_name'])}</div>")

                # Barcode Image
                if barcode_svg:
                    body_parts.append(f"<div class='thermal-barcode-box'>{barcode_svg}</div>")

                # Bottom row: SKU & Price
                bottom_items = []
                if preset.show_sku and item.get('sku'):
                    bottom_items.append(f"<span class='thermal-sku'>SKU: {html.escape(item['sku'])}</span>")
                if preset.show_price:
                    uom_str = f"/{html.escape(item['uom'])}" if preset.show_uom and item.get('uom') else ""
                    bottom_items.append(f"<span class='thermal-price'>{currency_symbol} {item['price']:,.2f}{uom_str}</span>")

                if bottom_items:
                    body_parts.append(f"<div class='thermal-bottom-row'>{' '.join(bottom_items)}</div>")

                body_parts.append("</div>")  # .thermal-label

            # Odd column empty padding
            if len(row_items) < cols:
                for _ in range(cols - len(row_items)):
                    body_parts.append(f"<div class='thermal-label' style='visibility:hidden;'></div>")

            body_parts.append("</div>")  # .thermal-row

        body_parts.append("</div>")  # .print-container
        body_parts.append(self._render_print_script(preset, flat_labels, currency_symbol, company_name))
        body_parts.append("</body></html>")

        return "".join(body_parts)

    def _render_print_script(self, preset, flat_labels, currency_symbol, company_name):
        """
        Default behaviour (unchanged): auto-open the OS print dialog.

        When a preset has 'Print Directly via Zebra Browser Print' enabled,
        try that first instead -- real ZPL sent straight to the default
        Zebra printer via the Browser Print local app, no dialog. If the
        app or its SDK file isn't present on this till, it falls back to
        the exact same window.print() behaviour as every other preset.
        """
        if not preset.use_browser_print:
            return "<script>window.addEventListener('load', () => { setTimeout(() => window.print(), 180); });</script>"

        zpl = build_zpl_document(flat_labels, preset, currency_symbol, company_name)
        zpl_json = json.dumps(zpl)
        return f"""
        <script src="/pos_retail/static/src/lib/browserprint/BrowserPrint-3.x.min.js"></script>
        <script>
        (function() {{
            const zpl = {zpl_json};
            function fallbackToDialog() {{ setTimeout(() => window.print(), 180); }}
            if (typeof BrowserPrint === "undefined") {{
                console.warn("[pos_retail] Zebra Browser Print SDK not found on this page -- " +
                    "falling back to the print dialog. See static/src/lib/browserprint/README.txt.");
                fallbackToDialog();
                return;
            }}
            BrowserPrint.getDefaultDevice("printer", function(device) {{
                if (!device) {{
                    console.warn("[pos_retail] Browser Print app has no default Zebra printer -- falling back.");
                    fallbackToDialog();
                    return;
                }}
                device.send(zpl, function() {{
                    console.log("[pos_retail] Label(s) sent to Zebra printer '" + device.name + "' via Browser Print.");
                }}, function(err) {{
                    console.error("[pos_retail] Browser Print failed to send ZPL, falling back to print dialog:", err);
                    fallbackToDialog();
                }});
            }}, function(err) {{
                console.error("[pos_retail] Browser Print app not reachable, falling back to print dialog:", err);
                fallbackToDialog();
            }});
        }})();
        </script>
        """
