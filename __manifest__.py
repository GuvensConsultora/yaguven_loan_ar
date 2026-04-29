{
    "name": "Yagüven — Préstamos AR (IVA + Sellos)",
    "version": "19.0.2.0.1",
    "category": "Accounting/Localizations/Argentina",
    "summary": "Extiende account_loans (Enterprise) con tratamiento impositivo argentino: IVA crédito fiscal sobre intereses devengados y sellos del contrato.",
    "description": """
Extensión multi-compañía de `account_loans` (Enterprise) para implementaciones argentinas.

Agrega:
* `tax_ids` en `account.loan.line` para devengar IVA crédito fiscal sobre el interés de cada cuota.
* `default_interest_tax_ids` en `account.loan` para propagar automáticamente el impuesto a las cuotas creadas.
* `stamp_tax_amount`, `stamp_tax_account_id`, `stamp_tax_partner_id` en `account.loan` para registrar
  los sellos del contrato como asiento separado en la fecha de toma del préstamo.

No reescribe métodos del nativo. Sobre `action_confirm` se intercepta tras `super()` para inyectar
las patas fiscales en los movimientos generados (si están en draft) o crear movimientos
complementarios (si ya fueron posteados).
""",
    "author": "Yagüven C.G.",
    "website": "https://yaguven.com.ar",
    "depends": [
        "account_loans",
        "l10n_ar",
    ],
    "data": [
        "views/account_loan_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
