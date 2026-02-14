# OneGroup Platform

Proyecto Django para holding empresarial multi-unidad de negocio (ONE GROUP matriz).

## Estructura

Apps incluidas:

- `core`: `BusinessUnit`, `UserProfile` (roles/permisos base).
- `crm`: `SalesRep`, `Lead`, `Sale`, `CallLog`.
- `inventory`: `Product`, `Supply`, `Equipment`, `SoftwareAsset`, `MarketingMaterial`.
- `finance`: `Commission`, `FinancingCalculatorLink`, `FinancialReport`.
- `rewards`: `Tier`, `CompensationPlan`, `PlanTierRule`, `RewardPoint`, `Bundle`, `Prize`, `Redemption`.
- `dashboard`: views/urls/templates para Admin/Manager/SalesRep.

## Reglas de compensación

Al confirmar una venta (`Sale.status=CONFIRMED`), se calcula automáticamente:

- `rule = PlanTierRule(plan=sale.plan, tier=sale.sales_rep.tier)`
- `commission = amount * commission_percent/100`
- `bonus = amount * bonus_percent/100`
- `points = amount * points_per_dollar`

Persistencia:

- Se crea `Commission` y `RewardPoint`.
- Idempotente por venta: no duplica cálculo si ya existen registros para la misma venta.

## Roles y alcance de datos

Orden vigente:

- `Partner`: vista global de plataforma (sin acceso a `/admin/`).
- `Administrador`: acceso acotado por `BusinessUnit`.
- `Asociado`: solo ve su propia información (ventas/puntos/call logs).

## Setup rápido

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py bootstrap_onegroup
python manage.py runserver
```

## Usuario admin inicial

Comando de seed crea:

- Usuario: `admin`
- Password: `ChangeMe123!`

Cámbialo inmediatamente en producción.

## Comandos útiles

```bash
# crear superusuario manual
python manage.py createsuperuser

# seed con credenciales personalizadas
python manage.py bootstrap_onegroup \
  --admin-username admin \
  --admin-email admin@onegroup.com \
  --admin-password 'StrongPassword!123'

# pruebas
python manage.py test

# validación
python manage.py check
```

## Dashboard mínimo

Rutas principales:

- `/` redirige por rol al dashboard correspondiente.
- `/admin-overview/` dashboard Admin/Manager.
- `/sales-overview/` dashboard SalesRep.
- `/sales/` lista de ventas.
- `/sales/<id>/` detalle de venta.
- `/points/` resumen de puntos.
- `/call-logs/` listado de call logs.
- `/call-logs/new/` crear call log.

Login:

- `/accounts/login/`

Admin Django:

- `/admin/`
