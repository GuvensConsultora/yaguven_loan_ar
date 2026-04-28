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
    yaguven_tax_move_id = fields.Many2one(
        "account.move",
        string="Asiento IVA",
        readonly=True,
        copy=False,
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

    def _yaguven_post_tax_move(self):
        """Crea un asiento companion: D IVA crédito / C cuenta del diario
        (típicamente banco). Idempotente: si ya existe el asiento vinculado,
        no hace nada."""
        self.ensure_one()
        if self.yaguven_tax_move_id:
            return
        if not self.tax_ids or not self.tax_amount:
            return
        loan = self.loan_id
        journal = loan.tax_journal_id or loan.journal_id
        contra_account = journal.default_account_id
        if not contra_account:
            raise UserError(_(
                "El diario «%(journal)s» no tiene cuenta default configurada. No "
                "se pudo asentar el IVA s/ interés de la cuota %(seq)s del préstamo "
                "«%(loan)s»."
            ) % {
                "journal": journal.display_name,
                "seq": self.sequence,
                "loan": loan.display_name,
            })
        res = self.tax_ids.compute_all(
            self.interest, currency=self.currency_id, quantity=1.0
        )
        tax_lines_vals = []
        for t in res["taxes"]:
            tax = self.env["account.tax"].browse(t["id"])
            tax_account = tax.invoice_repartition_line_ids.filtered(
                lambda r: r.repartition_type == "tax"
            ).account_id[:1]
            if not tax_account:
                raise UserError(_(
                    "El impuesto «%(tax)s» no tiene cuenta de IVA configurada en "
                    "su distribución de comprobantes."
                ) % {"tax": tax.display_name})
            tax_lines_vals.append((0, 0, {
                "account_id": tax_account.id,
                "name": _("IVA s/ interés — cuota %(seq)s — %(loan)s") % {
                    "seq": self.sequence,
                    "loan": loan.display_name,
                },
                "debit": t["amount"],
                "credit": 0.0,
                "tax_line_id": tax.id,
            }))
        total_tax = sum(t["amount"] for t in res["taxes"])
        if not tax_lines_vals or not total_tax:
            return
        move = self.env["account.move"].with_company(loan.company_id).create({
            "date": self.date,
            "journal_id": journal.id,
            "company_id": loan.company_id.id,
            "ref": _("IVA s/ interés — cuota %(seq)s — %(loan)s") % {
                "seq": self.sequence,
                "loan": loan.display_name,
            },
            "line_ids": tax_lines_vals + [(0, 0, {
                "account_id": contra_account.id,
                "name": _("IVA s/ interés — cuota %(seq)s") % {"seq": self.sequence},
                "debit": 0.0,
                "credit": total_tax,
            })],
        })
        move.action_post()
        self.yaguven_tax_move_id = move.id
