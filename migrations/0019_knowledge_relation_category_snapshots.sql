-- P07 hardening: preserve ontology category snapshots on every relation assertion.

ALTER TABLE memory_knowledge_relations ADD COLUMN IF NOT EXISTS from_category text;
ALTER TABLE memory_knowledge_relations ADD COLUMN IF NOT EXISTS to_category text;

UPDATE memory_knowledge_relations r
SET from_category=fi.category,to_category=ti.category
FROM memory_items fi,memory_items ti
WHERE fi.item_id=r.from_item_id AND ti.item_id=r.to_item_id
  AND (r.from_category IS NULL OR r.to_category IS NULL);

ALTER TABLE memory_knowledge_relations ALTER COLUMN from_category SET NOT NULL;
ALTER TABLE memory_knowledge_relations ALTER COLUMN to_category SET NOT NULL;
ALTER TABLE memory_knowledge_relations DROP CONSTRAINT IF EXISTS memory_knowledge_relations_from_category_check;
ALTER TABLE memory_knowledge_relations ADD CONSTRAINT memory_knowledge_relations_from_category_check CHECK(from_category IN (
  'FACT','HYPOTHESIS','EVIDENCE','OBSERVATION','INFERENCE','CORRELATION','CAUSE','PROCEDURE','DECISION','INTERVENTION','OUTCOME','EXPERIMENT','LEARNING','CONSTRAINT','OBJECTIVE'
));
ALTER TABLE memory_knowledge_relations DROP CONSTRAINT IF EXISTS memory_knowledge_relations_to_category_check;
ALTER TABLE memory_knowledge_relations ADD CONSTRAINT memory_knowledge_relations_to_category_check CHECK(to_category IN (
  'FACT','HYPOTHESIS','EVIDENCE','OBSERVATION','INFERENCE','CORRELATION','CAUSE','PROCEDURE','DECISION','INTERVENTION','OUTCOME','EXPERIMENT','LEARNING','CONSTRAINT','OBJECTIVE'
));

CREATE OR REPLACE FUNCTION memory_validate_knowledge_relation() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE from_tenant text; DECLARE to_tenant text; DECLARE from_cat text; DECLARE to_cat text;
DECLARE current_from_version text; DECLARE current_to_version text;
BEGIN
  SELECT tenant_id,category INTO from_tenant,from_cat FROM memory_items WHERE item_id=NEW.from_item_id;
  SELECT tenant_id,category INTO to_tenant,to_cat FROM memory_items WHERE item_id=NEW.to_item_id;
  IF from_tenant IS NULL OR to_tenant IS NULL THEN RAISE EXCEPTION 'knowledge relation endpoint memory not found'; END IF;
  IF from_tenant <> to_tenant THEN RAISE EXCEPTION 'cross-tenant knowledge relation forbidden' USING ERRCODE='42501'; END IF;
  SELECT version_id INTO current_from_version FROM memory_versions WHERE item_id=NEW.from_item_id ORDER BY version_no DESC LIMIT 1;
  SELECT version_id INTO current_to_version FROM memory_versions WHERE item_id=NEW.to_item_id ORDER BY version_no DESC LIMIT 1;
  IF NEW.from_version_id <> current_from_version OR NEW.to_version_id <> current_to_version THEN RAISE EXCEPTION 'knowledge relation must bind current versions'; END IF;
  IF NOT EXISTS(SELECT 1 FROM ontology_relation_rules r WHERE r.source_category=from_cat AND r.relation_type=NEW.relation_type AND r.target_category=to_cat) THEN
    RAISE EXCEPTION 'invalid ontology relation: % % %',from_cat,NEW.relation_type,to_cat USING ERRCODE='23514';
  END IF;
  NEW.tenant_id := from_tenant;
  NEW.from_category := from_cat;
  NEW.to_category := to_cat;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_guard_knowledge_relation_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF ROW(OLD.relation_id,OLD.tenant_id,OLD.from_item_id,OLD.from_version_id,OLD.from_category,OLD.relation_type,OLD.to_item_id,OLD.to_version_id,OLD.to_category,OLD.provenance,OLD.confidence,OLD.created_by,OLD.created_at)
     IS DISTINCT FROM ROW(NEW.relation_id,NEW.tenant_id,NEW.from_item_id,NEW.from_version_id,NEW.from_category,NEW.relation_type,NEW.to_item_id,NEW.to_version_id,NEW.to_category,NEW.provenance,NEW.confidence,NEW.created_by,NEW.created_at) THEN
    RAISE EXCEPTION 'knowledge relation assertions are immutable' USING ERRCODE='42501';
  END IF;
  IF OLD.status IS DISTINCT FROM NEW.status THEN
    IF NEW.status <> 'STALE' OR COALESCE(current_setting('app.ontology_relation_state_authorized',true),'') <> '1' THEN
      RAISE EXCEPTION 'knowledge relation status transition forbidden' USING ERRCODE='42501';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.15.1')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
