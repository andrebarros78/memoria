-- MEMORIA PLUS P15: second-generation InputGuard release contract.

INSERT INTO schema_meta(key,value) VALUES
  ('input_guard_version','IG-2.0.0'),
  ('input_guard_languages','en,pt,es,it,fr,de'),
  ('input_guard_encodings','PERCENT,HTML_ENTITY,UNICODE_ESCAPE,BASE64,URLSAFE_BASE64,HEX'),
  ('input_guard_structured_sources','MEMORY,ATTACHMENT,TOOL_OUTPUT,EXTERNAL_DOCUMENT,WEB_CONTENT'),
  ('input_guard_distributed_detection','true'),
  ('schema_version','memory-0.23.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
