# Factored_hackathon

## Demo web local

La demo visualiza el pipeline determinista de consulta de saldos usando
directamente el catálogo confiable y el motor de `evaluation/candidate_system.py`.
No agrega login real, base de datos, LLM ni llamadas externas. Desde la raíz del
repositorio, ejecútala con:

```text
.\.venv\Scripts\python.exe -m demo.app
```

Después abre <http://127.0.0.1:8000>. La pantalla permite probar una consulta,
sesión autenticada, sesión ausente y un propietario distinto. Muestra cada
etapa (`Intent`, `Product`, `Resolution`, `Authorization`, `Action`, `Outcome`),
el resultado grounded y la procedencia explícita del catálogo. Los casos no
autorizados muestran `No financial balance disclosed`; la resolución permanece
limitada al customer scope.