from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountLoanLine(models.Model):
    _inherit = "account.loan.line"

    tax_ids = fields.Many2many(
        "account.tax",
        "yaguven_loan_line_tax_rel",
        "line_id",
        "tax_id",
        string="Impuestos s/ interés",
        domain="[('type_tax_use','=','purchase'),('company_id','=',company_id)]",
        check_company=True,
    )
    tax_amount = fields.Monetary(
        string="IVA s/ interés",
        compute="_compute_tax_amount",
        store=True,
        currency_field="currency_id",
    )
    interest_with_tax = fields.Monetary(
        string="Interés c/ IVA",
        compute="_compute_tax_amount",
        store=True,
        currency_field="currency_id",
    )
    yaguven_vendor_bill_id = fields.Many2one(
        "account.move",
        string="Factura recibida (banco)",
        readonly=True,
        copy=False,
        help=(
            "Factura recibida (in_invoice) que respalda el crédito fiscal de IVA "
            "sobre el interés de la cuota. Generada en estado borrador al confirmar "
            "el préstamo, queda pendiente de validación contra el resumen físico "
            "del banco."
        ),
    )

    @api.depends("interest", "tax_ids")
    def _compute_tax_amount(self):
        for line in self:
            if not line.tax_ids or not line.interest:
                line.tax_amount = 0.0
                line.interest_with_tax = line.interest
                continue
            res = line.tax_ids.compute_all(
                line.interest,
                currency=line.currency_id,
                quantity=1.0,
                product=False,
                partner=False,
            )
            line.tax_amount = sum(t["amount"] for t in res["taxes"])
            line.interest_with_tax = res["total_included"]

    @api.model_create_multi
    def create(self, vals_list):
        loans = {}
        for vals in vals_list:
            if vals.get("tax_ids") or not vals.get("loan_id"):
                continue
            lid = vals["loan_id"]
            if lid not in loans:
                loans[lid] = self.env["account.loan"].browse(lid)
            loan = loans[lid]
            if loan.default_interest_tax_ids:
                vals["tax_ids"] = [(6, 0, loan.default_interest_tax_ids.ids)]
        return super().create(vals_list)

    def _yaguven_create_vendor_bill_draft(self, journal):
        """Crea factura recibida (in_invoice) en estado borrador con la línea de
        interés gravada. El asiento que generará al postearse es:

            D <expense_account_id del préstamo> (interés)        $interest
            D IVA crédito fiscal (de los tax_ids)                $tax_amount
                C <cuenta a pagar del partner banco>             $interest + $tax_amount

        Idempotente: si ya hay una factura vinculada, no hace nada."""
        self.ensure_one()
        if self.yaguven_vendor_bill_id:
            return
        if not self.tax_ids or not self.interest:
            return
        loan = self.loan_id
        if not loan.partner_id:
            raise UserError(_(
                "El préstamo «%s» no tiene partner (banco proveedor) asignado. "
                "No se puede generar la factura recibida del banco."
            ) % loan.display_name)
        if not loan.expense_account_id:
            raise UserError(_(
                "El préstamo «%s» no tiene cuenta de gasto interés (expense_account_id) "
                "configurada. La factura recibida no puede armarse."
            ) % loan.display_name)
        line_name = _(
            "Interés préstamo %(loan)s — cuota %(seq)s (%(date)s)"
        ) % {"loan": loan.display_name, "seq": self.sequence, "date": self.date}
        bill_vals = {
            "move_type": "in_invoice",
            "partner_id": loan.partner_id.id,
            "company_id": loan.company_id.id,
            "journal_id": journal.id,
            "date": self.date,
            "invoice_date": self.date,
            "ref": _("Resumen %(loan)s — cuota %(seq)s") % {
                "loan": loan.display_name,
                "seq": self.sequence,
            },
            "invoice_line_ids": [(0, 0, {
                "name": line_name,
                "account_id": loan.expense_account_id.id,
                "quantity": 1.0,
                "price_unit": self.interest,
                "tax_ids": [(6, 0, self.tax_ids.ids)],
            })],
        }
        bill = self.env["account.move"].with_company(loan.company_id).create(bill_vals)
        self.yaguven_vendor_bill_id = bill.id
