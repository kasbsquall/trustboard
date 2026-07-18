# Notas verificadas de la hackathon (revisadas el 17 de julio de 2026)

Fuente: https://datahub.devpost.com/ , /rules y /resources.

## Fechas
- Submission: 6 de julio (9:00am ET) al 10 de agosto de 2026 (5:00pm ET).
- Judging: 17 al 31 de agosto de 2026. Ganadores: alrededor del 8 de septiembre.

## Entregables obligatorios
- Video demo de menos de 3 minutos, publico en YouTube, Vimeo o Youku, mostrando el proyecto funcionando.
- Repo publico con todo el codigo, assets e instrucciones. Licencia Apache 2.0 incluida (requisito explicito).
- Descripcion de texto: features, funcionalidad, tecnologias, fuentes de datos.
- Acceso funcional para jueces: demo en vivo, app hosteada o repo con setup claro, gratis y sin restricciones.
- Recomendado: carpeta examples/ con outputs de muestra.
- Todo en ingles o con traducciones.

## Regla New Projects Only
"Projects must be newly created during the Submission Period." Se permiten frameworks,
librerias, templates y asistentes de IA, pero cualquier codigo preexistente debe declararse.

## Categoria elegida
Agents That Do Real Work: el agente accede a DataHub via MCP Server o Agent Context Kit,
entiende relaciones de datos, ejecuta acciones y escribe resultados de vuelta para el
siguiente usuario o agente.

## Criterios de juzgamiento (peso igual)
1. Use of DataHub (grafo de contexto: lineage, ownership, schemas, governance signals)
2. Technical Execution (end-to-end, robustez)
3. Originality
4. Real-World Usefulness
5. Submission Quality
Bonus: contribuciones open source significativas a DataHub.

## Recursos oficiales
- Quickstart: https://docs.datahub.com/docs/quickstart
- MCP Server: https://github.com/acryldata/mcp-server-datahub
- Agent Context Kit: https://docs.datahub.com/docs/dev-guides/agent-context/agent-context
- DataHub Skills docs: https://docs.datahub.com/docs/dev-guides/agent-context/skills
- DataHub Skills repo: https://github.com/datahub-project/datahub-skills
- Analytics Agent: https://docs.datahub.com/docs/features/feature-guides/analytics-agent
- DataHub Core: https://github.com/datahub-project/datahub

## Datapacks
- showcase-ecommerce: 1,049 entidades (Snowflake, Looker, PowerBI, Tableau, dbt, Spark,
  PostgreSQL, S3). Cargar con: datahub datapack load showcase-ecommerce
  Pendiente verificar al cargarlo: que dominios trae (la pagina no los lista).
- bootstrap: starter ligero (datasets, dashboards, users, tags).
- Datasets con escenarios sembrados (alternativas para demo):
  - nyc-taxi (problemas de freshness): github.com/datahub-project/static-assets/tree/main/datasets/nyc-taxi
  - healthcare (problemas de calidad): github.com/datahub-project/static-assets/tree/main/datasets/healthcare
  - fiction-retail (retail sintetico, 10 tablas)

## Soporte
- Slack de DataHub, canal #agent-hackathon.
- Contacto del hackathon: lakshay@datahub.com. Devpost: support@devpost.com.

## Premios
$20,500 en total. Grand Prize $6,000. Challenge Winners $3,000 x 4.
Honourable Mention $1,000 x 2. Feedback Survey $50 x 10.
