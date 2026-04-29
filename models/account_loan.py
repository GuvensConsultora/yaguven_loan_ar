from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountLoan(models.Model):
    _inherit = "account.loan"

    partner_id = fields.Many2one(
        "res.partner",
        string="Banco (proveedor)",
        check_company=False,
        help=(
            "Entidad bancaria como proveedor. Se usa como partner de las facturas "
            "recibidas (in_invoice) que generan el crédito fiscal de IVA mes a mes."
        ),
    )
    purchase_journal_id = fields.Many2one(
        "account.journal",
        string="Diario de compras (banco)",
        check_company=True,
        domain="[('type','=','purchase')]",
        help=(
            "Diario tipo *Compras* donde se generan las facturas recibidas mensuales "
            "del banco con el crédito fiscal de IVA sobre el interés de cada cuota. "
            "Si se deja vacío, se usa el primer diario de compras de la compañía."
        ),
    )
    default_interest_tax_ids = fields.Many2many(
        "account.tax",
        "yaguven_loan_default_tax_rel",
        "loan_id",
        "tax_id",
        string="Impuestos s/ interés (default)",
        domain="[('type_tax_use','=','purchase'),('company_id','=',company_id)]",
        check_company=True,
        help=(
            "Impuestos de compras a propagar como default a cada cuota generada. "
            "Típicamente IVA 21% compras (servicios financieros bancarios, art. 3 "
            "inc. e ap. 21 LIVA + art. 7 inc. h ap. 16 — gravados, no exentos)."
        ),
    )
    stamp_tax_amount = fields.Monetary(
        string="Sellos del contrato",
        currency_field="currency_id",
        help=(
            "Monto del impuesto provincial de sellos sobre el contrato de mutuo, "
            "habitualmente retenido por la entidad bancaria al desembolsar el préstamo."
        ),
    )
    stamp_tax_account_id = fields.Many2one(
        "account.account",
        string="Cuenta de Sellos",
        check_company=True,
        domain="[('account_type','=','expense')]",
    )
    stamp_tax_journal_id = fields.Many2one(
        "account.journal",
        string="Diario para sellos",
        check_company=True,
        domain="[('type','in',('general','bank'))]",
        help=(
            "Diario donde se asienta el sellos. Si se deja vacío, se usa el diario "
            "del préstamo. La contrapartida es la cuenta default del diario "
            "(habitualmente banco)."
        ),
    )

    def action_confirm(self):
        res = super().action_confirm()
        for loan in self:
            loan._yaguven_propagate_default_taxes()
            loan._yaguven_post_stamp_tax_move()
            loan._yaguven_create_interest_vendor_bills()
        return res

    def _yaguven_propagate_default_taxes(self):
        self.ensure_one()
        if not self.default_interest_tax_ids:
            return
        empty_lines = self.env["account.loan.line"].search([
            ("loan_id", "=", self.id),
            ("tax_ids", "=", False),
        ])
        if empty_lines:
            empty_lines.write({"tax_ids": [(6, 0, self.default_interest_tax_ids.ids)]})

    def _yaguven_post_stamp_tax_move(self):
        self.ensure_one()
        if not self.stamp_tax_amount:
            return
        if not self.stamp_tax_account_id:
            raise UserError(_(
                "Cargaste %(amount)s de sellos en el préstamo «%(loan)s» pero no "
                "indicaste la cuenta de imputación. Definí «Cuenta de Sellos» antes de "
                "confirmar."
            ) % {
                "amount": self.stamp_tax_amount,
                "loan": self.display_name,
            })
        journal = self.stamp_tax_journal_id or self.journal_id
        contra_account = journal.default_account_id
        if not contra_account:
            raise UserError(_(
                "El diario «%(journal)s» no tiene cuenta default configurada. No "
                "se pudo asentar el sellos del préstamo «%(loan)s»."
            ) % {
                "journal": journal.display_name,
                "loan": self.display_name,
            })
        move = self.env["account.move"].with_company(self.company_id).create({
            "date": self.date,
            "journal_id": journal.id,
            "company_id": self.company_id.id,
            "ref": _("Sellos contrato préstamo %s") % self.display_name,
            "line_ids": [
                (0, 0, {
                    "account_id": self.stamp_tax_account_id.id,
                    "name": _("Sellos contrato préstamo %s") % self.display_name,
                    "debit": self.stamp_tax_amount,
                    "credit": 0.0,
                }),
                (0, 0, {
                    "account_id": contra_account.id,
                    "name": _("Sellos contrato préstamo %s") % self.display_name,
                    "debit": 0.0,
                    "credit": self.stamp_tax_amount,
                }),
            ],
        })
        move.action_post()

    def _yaguven_create_interest_vendor_bills(self):
        """Por cada cuota con `tax_ids` cargados, crea una factura recibida
        (in_invoice) **en estado borrador** contra el banco como proveedor.
        Queda en draft hasta que el contador la confronte y postee con el
        resumen mensual del banco. Al postearla entra al libro IVA Compras."""
        self.ensure_one()
        if not self.partner_id:
            return
        journal = self.purchase_journal_id or self.env["account.journal"].search(
            [("company_id", "=", self.company_id.id), ("type", "=", "purchase")],
            limit=1,
        )
        if not journal:
            raise UserError(_(
                "No hay diario tipo *Compras* en la compañía %s para el préstamo "
                "«%s». Configurá uno antes de confirmar."
            ) % (self.company_id.display_name, self.display_name))
        loan_lines = self.env["account.loan.line"].search([
            ("loan_id", "=", self.id),
            ("tax_ids", "!=", False),
        ])
        for line in loan_lines:
            line._yaguven_create_vendor_bill_draft(journal)
