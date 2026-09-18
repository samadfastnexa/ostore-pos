# -*- coding: utf-8 -*-
import hashlib
import hmac
from odoo import http
from odoo.http import request


def get_security_token(env, prefix, res_id):
    secret = env['ir.config_parameter'].sudo().get_param('database.secret', 'pos_retail_khata')
    msg = f'{prefix}_{res_id}'.encode('utf-8')
    return hmac.new(secret.encode('utf-8'), msg, hashlib.sha256).hexdigest()[:16]


def get_ledger_token(env, partner_id):
    return get_security_token(env, 'ledger_partner', partner_id)


MODEL_REPORT_MAP = {
    'sale.order': 'sale.action_report_saleorder',
    'account.move': 'account.account_invoices',
    'purchase.order': 'purchase.action_report_purchaseorder',
    'stock.picking': 'stock.action_report_delivery',
    'account.payment': 'pos_retail.action_report_payment_receipt',
    'pos.order': 'pos_retail.action_report_pos_receipt_a4',
    'pos.retail.customer.refund': 'pos_retail.action_report_customer_refund_receipt',
    'pos.retail.vendor.return': 'pos_retail.action_report_vendor_return_receipt',
    'res.partner': 'pos_retail.report_customer_ledger',
}


class PosRetailPortalLedger(http.Controller):

    @http.route([
        '/pos_retail/portal/ledger/pdf/<int:partner_id>',
        '/pos_retail/portal/vendor/pdf/<int:partner_id>',
    ], type='http', auth='public', website=False)
    def download_public_ledger_pdf(self, partner_id, token=None, **kwargs):
        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return request.not_found()

        expected_token = get_ledger_token(request.env, partner_id)
        # Verify security token or active logged-in user session
        if token != expected_token and not request.session.uid:
            return request.make_response('Unauthorized access', status=403)

        is_vendor = '/vendor/' in request.httprequest.path
        report_name = 'pos_retail.report_vendor_statement' if is_vendor else 'pos_retail.report_customer_ledger'

        try:
            pdf = request.env['ir.actions.report'].sudo()._render_qweb_pdf(report_name, [partner.id])[0]
            clean_name = (partner.name or 'Partner').replace(' ', '_')
            prefix = 'Vendor_Statement' if is_vendor else 'Customer_Ledger'
            filename = f'{prefix}_{clean_name}.pdf'

            headers = [
                ('Content-Type', 'application/pdf'),
                ('Content-Length', len(pdf)),
                ('Content-Disposition', f'inline; filename={filename}'),
            ]
            return request.make_response(pdf, headers=headers)
        except Exception as e:
            return request.make_response(f'Error generating statement: {str(e)}', status=500)

    @http.route('/pos_retail/portal/customer_refund/pdf/<int:refund_id>', type='http', auth='public', website=False)
    def download_public_customer_refund_pdf(self, refund_id, token=None, **kwargs):
        refund = request.env['pos.retail.customer.refund'].sudo().browse(refund_id)
        if not refund.exists():
            return request.not_found()

        expected_token = get_security_token(request.env, 'customer_refund', refund_id)
        if token != expected_token and not request.session.uid:
            return request.make_response('Unauthorized access', status=403)

        try:
            pdf = request.env['ir.actions.report'].sudo()._render_qweb_pdf('pos_retail.action_report_customer_refund_receipt', [refund.id])[0]
            clean_name = (refund.name or 'Refund').replace('/', '_')
            filename = f'Customer_Refund_{clean_name}.pdf'
            headers = [
                ('Content-Type', 'application/pdf'),
                ('Content-Length', len(pdf)),
                ('Content-Disposition', f'inline; filename={filename}'),
            ]
            return request.make_response(pdf, headers=headers)
        except Exception as e:
            return request.make_response(f'Error generating customer refund receipt: {str(e)}', status=500)

    @http.route('/pos_retail/portal/vendor_return/pdf/<int:return_id>', type='http', auth='public', website=False)
    def download_public_vendor_return_pdf(self, return_id, token=None, **kwargs):
        ret = request.env['pos.retail.vendor.return'].sudo().browse(return_id)
        if not ret.exists():
            return request.not_found()

        expected_token = get_security_token(request.env, 'vendor_return', return_id)
        if token != expected_token and not request.session.uid:
            return request.make_response('Unauthorized access', status=403)

        try:
            pdf = request.env['ir.actions.report'].sudo()._render_qweb_pdf('pos_retail.action_report_vendor_return_receipt', [ret.id])[0]
            clean_name = (ret.name or 'Vendor_Return').replace('/', '_')
            filename = f'Vendor_Return_{clean_name}.pdf'
            headers = [
                ('Content-Type', 'application/pdf'),
                ('Content-Length', len(pdf)),
                ('Content-Disposition', f'inline; filename={filename}'),
            ]
            return request.make_response(pdf, headers=headers)
        except Exception as e:
            return request.make_response(f'Error generating vendor return receipt: {str(e)}', status=500)

    @http.route([
        '/pos_retail/portal/receipt/pdf/<int:order_id>',
        '/pos_retail/portal/receipt/pdf/<string:order_key>',
    ], type='http', auth='public', website=False)
    def download_public_pos_receipt_pdf(self, order_id=None, order_key=None, token=None, **kwargs):
        env = request.env
        key = order_id or order_key
        order = None
        if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
            order = env['pos.order'].sudo().browse(int(key))
            expected_token = get_security_token(env, 'pos_receipt', order.id) if order.exists() else None
            if token != expected_token and not request.session.uid:
                return request.make_response('Unauthorized access', status=403)
        else:
            order = env['pos.order'].sudo().search([('access_token', '=', key)], limit=1)
            if not order:
                return request.not_found()

        if not order or not order.exists():
            return request.not_found()

        try:
            fmt = kwargs.get('format', 'a4')
            report_name = 'pos_retail.report_pos_receipt_thermal' if fmt == 'thermal' else 'pos_retail.report_pos_receipt_a4'
            pdf = env['ir.actions.report'].sudo()._render_qweb_pdf(report_name, [order.id])[0]
            clean_name = (order.pos_reference or order.name or f'Order_{order.id}').replace('/', '-').replace(' ', '_')
            prefix = 'Credit_Return' if order.is_refund else 'Receipt'
            filename = f'{prefix}_{clean_name}.pdf'
            headers = [
                ('Content-Type', 'application/pdf'),
                ('Content-Length', len(pdf)),
                ('Content-Disposition', f'inline; filename={filename}'),
            ]
            return request.make_response(pdf, headers=headers)
        except Exception as e:
            return request.make_response(f'Error generating receipt PDF: {str(e)}', status=500)

    @http.route('/pos_retail/portal/payment/pdf/<int:payment_id>', type='http', auth='public', website=False)
    def download_public_payment_receipt_pdf(self, payment_id, token=None, **kwargs):
        env = request.env
        payment = env['account.payment'].sudo().browse(payment_id)
        if not payment.exists():
            return request.not_found()

        expected_token = get_security_token(env, 'pos_payment', payment_id)
        if token != expected_token and not request.session.uid:
            return request.make_response('Unauthorized access', status=403)

        try:
            pdf = env['ir.actions.report'].sudo()._render_qweb_pdf('pos_retail.report_pos_retail_payment_receipt', [payment.id])[0]
            clean_name = (payment.name or f'Payment_{payment.id}').replace('/', '-').replace(' ', '_')
            filename = f'Payment_Receipt_{clean_name}.pdf'
            headers = [
                ('Content-Type', 'application/pdf'),
                ('Content-Length', len(pdf)),
                ('Content-Disposition', f'inline; filename={filename}'),
            ]
            return request.make_response(pdf, headers=headers)
        except Exception as e:
            return request.make_response(f'Error generating payment receipt PDF: {str(e)}', status=500)

    @http.route('/pos_retail/portal/doc/pdf/<string:model_name>/<int:res_id>', type='http', auth='public', website=False)
    def download_public_document_pdf(self, model_name, res_id, token=None, report=None, **kwargs):
        env = request.env
        expected_token = get_security_token(env, model_name, res_id)
        if token != expected_token and not request.session.uid:
            return request.make_response('Unauthorized access', status=403)

        record = env[model_name].sudo().browse(res_id)
        if not record.exists():
            return request.not_found()

        report_name = report or MODEL_REPORT_MAP.get(model_name)
        if not report_name:
            return request.make_response(f'No report configured for {model_name}', status=400)

        try:
            pdf = env['ir.actions.report'].sudo()._render_qweb_pdf(report_name, [record.id])[0]
            clean_name = (record.display_name or getattr(record, 'name', '') or f'{model_name}_{record.id}').replace('/', '-').replace(' ', '_')
            filename = f'{clean_name}.pdf'
            headers = [
                ('Content-Type', 'application/pdf'),
                ('Content-Length', len(pdf)),
                ('Content-Disposition', f'inline; filename={filename}'),
            ]
            return request.make_response(pdf, headers=headers)
        except Exception as e:
            return request.make_response(f'Error generating document PDF: {str(e)}', status=500)

    @http.route('/pos_retail/portal/get_doc_share_info', type='jsonrpc', auth='user')
    def get_doc_share_info(self, model_name, res_id, **kwargs):
        env = request.env
        token = get_security_token(env, model_name, res_id)
        base_url = request.httprequest.url_root.rstrip('/')
        if base_url.startswith('http://') and not ('localhost' in base_url or '127.0.0.1' in base_url):
            base_url = 'https://' + base_url[7:]
        if model_name == 'pos.order':
            order = env['pos.order'].sudo().browse(res_id)
            if order.exists() and order.access_token:
                pdf_url = f"{base_url}/pos_retail/portal/receipt/pdf/{order.access_token}"
            else:
                pdf_url = f"{base_url}/pos_retail/portal/receipt/pdf/{res_id}?token={token}"
        elif model_name == 'res.partner':
            partner = env['res.partner'].sudo().browse(res_id)
            is_vendor = bool(partner.supplier_rank and not partner.customer_rank)
            route_part = 'vendor' if is_vendor else 'ledger'
            pdf_url = f"{base_url}/pos_retail/portal/{route_part}/pdf/{res_id}?token={token}"
        elif model_name == 'pos.retail.customer.refund':
            pdf_url = f"{base_url}/pos_retail/portal/customer_refund/pdf/{res_id}?token={token}"
        elif model_name == 'pos.retail.vendor.return':
            pdf_url = f"{base_url}/pos_retail/portal/vendor_return/pdf/{res_id}?token={token}"
        elif model_name == 'account.payment':
            pdf_url = f"{base_url}/pos_retail/portal/payment/pdf/{res_id}?token={token}"
        else:
            pdf_url = f"{base_url}/pos_retail/portal/doc/pdf/{model_name}/{res_id}?token={token}"

        return {
            'token': token,
            'pdf_url': pdf_url,
        }

    @http.route('/pos_retail/print_report', type='http', auth='user', website=False)
    def direct_print_report(self, report, id, **kwargs):
        """
        Renders a report as HTML with an embedded auto-print script.
        Directly opens the browser's printer dialog upon loading,
        without triggering a file download.
        """
        env = request.env
        doc_id = int(id)
        report_record = env['ir.actions.report'].sudo()._get_report_from_name(report)
        if not report_record:
            report_record = env.ref(report, raise_if_not_found=False)
        if not report_record:
            return request.not_found(f"Report {report} not found.")

        try:
            report_name = report_record.report_name
            html_bytes = report_record._render_qweb_html(report_name, [doc_id])[0]
            html_content = html_bytes.decode('utf-8', errors='ignore') if isinstance(html_bytes, bytes) else html_bytes

            auto_print_script = """
            <style>
                @media print {
                    @page { margin: 2mm; }
                    .no-print { display: none !important; }
                }
                .pos-retail-print-toolbar {
                    position: fixed;
                    top: 10px;
                    right: 10px;
                    z-index: 99999;
                    background: rgba(15, 23, 42, 0.85);
                    padding: 8px 14px;
                    border-radius: 8px;
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                    display: flex;
                    gap: 8px;
                    align-items: center;
                }
                .pos-retail-print-toolbar button {
                    background: #2563eb;
                    color: white;
                    border: none;
                    padding: 6px 14px;
                    border-radius: 6px;
                    font-weight: 600;
                    cursor: pointer;
                    font-size: 13px;
                }
                .pos-retail-print-toolbar button:hover {
                    background: #1d4ed8;
                }
                .pos-retail-print-toolbar .btn-close-tab {
                    background: #64748b;
                }
                .pos-retail-print-toolbar .btn-close-tab:hover {
                    background: #475569;
                }
            </style>
            <div class="no-print pos-retail-print-toolbar">
                <button onclick="window.print()">🖨️ Open Printer</button>
                <button class="btn-close-tab" onclick="window.close()">Close</button>
            </div>
            <script type="text/javascript">
                (function() {
                    function doPrint() {
                        setTimeout(function() {
                            window.focus();
                            window.print();
                        }, 250);
                    }
                    if (document.readyState === 'complete') {
                        doPrint();
                    } else {
                        window.addEventListener('load', doPrint);
                    }
                })();
            </script>
            """

            if "</body>" in html_content:
                html_content = html_content.replace("</body>", f"{auto_print_script}</body>")
            else:
                html_content += auto_print_script

            return request.make_response(html_content, headers=[
                ('Content-Type', 'text/html; charset=utf-8'),
                ('Cache-Control', 'no-cache, no-store, must-revalidate'),
            ])
        except Exception as e:
            return request.make_response(f"Error rendering printable report: {str(e)}", status=500)
