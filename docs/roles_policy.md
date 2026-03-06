# Politica de Roles One-Group

## Jerarquia y prioridad

- PARTNER: 100
- ADMINISTRADOR: 90
- JR_PARTNER: 85
- BUSINESS_MANAGER: 80
- ELITE_MANAGER: 70
- SENIOR_MANAGER: 60
- MANAGER: 50
- SOLAR_ADVISOR: 40
- SOLAR_CONSULTANT: 30

Regla base:

- `puede_gestionar(A, B) = prioridad(A) > prioridad(B)`

## Alcance minimo

- Partner: visibilidad y gestion total.
- Administrador: operacion global segun politica de Partner.
- Business/Elite/Senior/Manager: gestion de su arbol descendente.
- Solar Advisor: gestion de consultores descendentes.
- Solar Consultant: solo su propio alcance.

## Seguridad

- Prohibida autoescalacion de privilegios.
- Todo cambio de rol debe registrarse en `RoleChangeAudit`.
- Permisos se asignan por modulo/accion con principio de minimo privilegio.

## Operacion

- Semilla inicial: `python manage.py seed_rbac`.
- Bootstrap integral: `python manage.py bootstrap_onegroup`.
- Verificacion de tests RBAC: `python manage.py test core`.
