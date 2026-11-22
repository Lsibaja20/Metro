# MetroCal Web — Gestión metrológica (prototipo web académico)

Trabajo final del curso II-0806 Metrología y Normalización. Empresa e instrumentos ficticios. La herramienta sirve para demostrar gestión de intervalos de calibración, registro histórico, análisis de riesgos, verificación documental. **No es un software certificado ni se debe usar sin revisión técnica para decisiones metrológicas reales.**

## Instalación en Visual Studio Code (Windows)

1. Descomprime **MetroCal_Web_Sin_Economia.zip**. Abre la carpeta **MetroCal_Web_Sin_Economia** en VS Code (Archivo > Abrir carpeta).
2. Instala Python y la extensión *Python* de Microsoft para VS Code.
3. Abre la terminal de VS Code y escribe `py app.py` (o `python app.py`). También funciona con **F5**.
4. Abre http://127.0.0.1:8765 si no se abre automáticamente.
5. Usuario: **admin**. Contraseña: **MetroCal2026!**. Cierra el servidor con Ctrl+C.

**IMPORTANTE:** El archivo `app.py` está directamente dentro de la carpeta `MetroCal_Web_Sin_Economia`; no tienes que entrar a una subcarpeta adicional. Si el puerto 8765 está ocupado (por la versión anterior), cierra el servidor anterior con Ctrl+C antes de iniciar este.

## ¿Qué cambia respecto de la primera versión?

- Conserva interfaz moderna, inicio de sesión local, panel, inventario editable, historial de calibraciones, gráficas, métodos escalera y deriva, aprobación trazable y CSV.
- **Evaluación de riesgos:** cinco factores de 1 a 3: intensidad de uso, ambiente, impacto, estabilidad y verificaciones intermedias. Clasifica 5–7 bajo, 8–11 medio, 12–15 alto. Exige responsable y controles. Estos cortes son una propuesta académica, no exigencias de una norma.
- **Control en los cálculos:** bloquea recomendaciones de **ampliación** si no hay evaluación de riesgo registrada o el riesgo es alto. Se mantiene la aprobación manual documentada; para reducir intervalos no se exige la evaluación como bloqueo.
- **Verificación normativa:** muestra una lista de 5 puntos para apoyar la revisión documental relacionada con ISO 9001:2015 7.1.5.2; exige registrar quién verificó y referencias de evidencia. El sistema **no** certifica cumplimiento de ISO 9001 ni comprueba por sí mismo que el certificado exista o sea válido.
- **Pruebas automáticas:** `py -m unittest -v`.

## Orden sugerido para demostrar la plataforma

1. Entrar al sistema y revisar indicadores de equipos.
2. Abrir Inventario y escoger un instrumento, luego revisar su historial.
3. En **Evaluación de riesgos**, registrar valores, medidas y responsable.
4. En **Análisis de intervalos**, elegir el instrumento, método escalera y calcular. Un intento de ampliar sin riesgo evaluado debe bloquearse. Con riesgo bajo o medio se habilita propuesta sujeta a aprobación.
5. Aprobar con justificación técnica y responsable si procede.
6. En **Verificación normativa**, documentar evidencias disponibles, marcando solo las efectivamente demostradas.

## Interpretación metrológica y límites

- La regla *escalera* utiliza la regla didáctica de la clase: porcentaje `|error| / EMP × 100`, umbral 80%, cambio ilustrativo del 50%, máximo de 36 meses en ampliaciones. El cálculo usa un EMP positivo como magnitud de límite; **EMP y tolerancia del proceso no son equivalentes**.
- La *deriva* toma dos calibraciones sucesivas y estima una pendiente lineal. Utiliza el margen `EMP − |error actual| − U` para proponer un intervalo ilustrativo. No equivale a una carta de control estadística completa y no extrapola después de un ajuste.
- `|error| + U > EMP` se utiliza únicamente como **alerta conservadora de revisión**, no como regla de decisión universal. La conformidad formal requiere regla acordada y análisis de incertidumbre adecuados.
- La evaluación de riesgos y la lista normativa dependen de datos que introduce el usuario: introducir o marcar algo no constituye evidencia independiente.
- La recomendación no se aplica automáticamente: requiere aprobación documentada.
- El apartado **ISO 9001:2015 7.1.5.2** es un **candidato de requisito normativo**: deben presentarlo a la profesora para su aprobación, como pide la guía del trabajo final. La guía ILAC-G24/OIML D 10 es referencia técnica, no periodicidad obligatoria.
- **Seguridad:** sistema local para demostración, sin HTTPS, roles empresariales, CSRF, copias automatizadas, controles de edición concurrente ni seguridad para Internet. **No publicar en Internet** sin trabajo adicional. Cambia la contraseña de demostración antes de utilizar datos no ficticios.

## Versión Streamlit (publicada en internet)

- `streamlit_app.py`: misma plataforma con interfaz Streamlit. Usa exactamente los mismos cálculos, reglas y base de datos de `app.py`.
- Ejecutar localmente: `pip install -r requirements.txt` y luego `streamlit run streamlit_app.py`.
- Publicar: en share.streamlit.io → *Create app* → repositorio `Metro`, rama `main`, archivo principal `streamlit_app.py`.
- En Streamlit Community Cloud la base `metrocal.sqlite3` se reinicia cuando la app se reinicia o se actualiza: sirve para demostración, no para guardar datos permanentes.

## Estructura del proyecto

- `app.py`: servidor local, base SQLite, API y métodos de cálculo (biblioteca estándar de Python).
- `static/index.html`: diseño de plataforma.
- `static/app.js`: lógica de formularios, paneles y gráficas.
- `static/style.css`: estilos visuales responsivos.
- `test_metrocal.py`: pruebas automatizadas.
- `.vscode/launch.json`: ejecutar con F5 desde VS Code.
- `metrocal.sqlite3`: se crea al primer inicio, almacena la información. **Para reiniciar la demostración**, detén el servidor y elimina este archivo (se borrarán los cambios realizados).

No se necesitan paquetes pip. Se usa una fuente web opcional; la interfaz tiene fuente alternativa sin conexión.

## Mejoras metrológicas de MetroCal Web
- **Verificaciones intermedias**: nuevas comprobaciones fechadas con referencia, lectura, incertidumbre, patrón y responsable; muestra alertas orientativas y evita ampliar intervalos cuando la última comprobación arroja una alerta.
- **Trazabilidad documental**: número de certificado, laboratorio y patrón de referencia al guardar una calibración.
- **Comparación de métodos**: botón en Análisis de intervalos para visualizar conjuntamente propuestas escalera y deriva, incluidos bloqueos y datos insuficientes.
- La norma INTE/ISO/IEC 17025:2017 (6.4.7 y 6.4.10), el VIM y la GUM fundamentan el informe, pero esta plataforma no asegura por sí sola su cumplimiento integral.
- Abre el navegador automáticamente y muestra la misma información de acceso en terminal que la primera versión.
