import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXPECTED={
 '0001_base':'ae2b3bc1e7609828127a521603afb7bfa113dd85fe45b2734b0d88a3a62ff8ec',
 '0002_m0_canonical':'307588ef97faa13d2d4019d82412baebbcb5d6d2f714b43ba431e5790a7a78a2',
 '0003_m1_retrieval':'82cdf80d5ec7feeb8ed3d7bca6c11d7f3a876ae08ae7f13f027ff243318288df',
 '0004_m1_pgvector':'f8b21339f18642fb310247208a790f5ad596396367b41fc387ab642ff5f124dc',
 '0005_m2_continuity':'cd306e74737d473e1d83c1ae60b883ce2bd5a0c51ad1357df2123775c7494545',
 '0006_m3_tenant_rls':'197f228e4c535720f14609dbfb051365bbcb3fd0de952045aed408d84ccba575',
 '0007_m5_multiagent':'b17537c6e5f3f076c995eb27b02d242df5dbceadb02166a9c8099e0536fbaeb2',
 '0008_governor_contract':'4ea876f5e3df3bd0cb98c55655249b4a73d25fdc2099d79b7036f2af6be22fba',
 '0009_external_conversation_resolver':'19be14045e0449f971ea42112247cf9bed5b4721317307f15d646a58064571f2',
 '0010_conversation_ingestion':'850d18b13d7aae3aed94718d564c8bea6567f2d52f2e4cf6e0a7ff6d191aca69',
 '0011_runtime_role_grants':'49912d0c7f40586b2bede7174b4902264bca1b840a58430d6c9cfeb7f9911f9e',
 '0012_trust_and_outcome_learning':'33f6e8e42b7f1ded69ddf01a8b7f279b6fdeeeea574ebf6c8cac0b486f720c37',
 '0013_embedding_stale':'7c8b1f6f6fe54135cc53751e8f2e6d5f4fa3bef7ec85f06934f967016cfaefc3',
 '0014_version_bound_learning_policy':'f0920eb719409f4cc0af46bba5f00c2c6227f84ee2cf331823522d5a746efac4',
 '0015_universal_auth_and_derived_dependencies':'4601800c7d6f7bf7299e9902cb4bde4fdb7fc72b7618ed354c912a60f2482205',
 '0016_decommission_legacy_governor_auth':'e72e6542bf3bdb889c5e1b6082fe4cd22ab2159669df4ab73529d4f23f4ad19c',
 '0017_reconcile_legacy_governor_bindings':'7ded6ed96efdf31ea18267ce73955f80143db306371225d4156994f298bd3050',
 '0018_formal_knowledge_ontology':'8517f1c8679ed9329ef7e10fc6491fc31403b71b559bfdbc86c924eb3d801418',
 '0019_knowledge_relation_category_snapshots':'77c7f901162e21f4ebd555cfa24fe94aabb949ddf16a5d2254fcd454867990c7',
 '0020_fix_ontology_transition_function':'20f8a43278c029491c2382d6073e6603f92e90cbdd74c9263472cf143d570260',
 '0021_complete_experience_graph':'742ab7043d8b84b16acf589766a0cfc0dd4ef5d84f52b1f4aabd75757aa14f99',
 '0022_fix_experience_graph_edge_validation':'a34a62c4b6fb8267df113eebde0f22f0c7c740f67fc3480530ae0ea9174f82ac',
 '0023_causal_memory_policy':'696ee480795ced3fa49c2e9751c7315dd3420a65bdcf5d894df25a887f741d34',
 '0024_formal_sovereign_decisions':'f0f352fda3d1c5063f7a9d0890c1139071fc8139686dac63b3b37d199fc51966',
 '0025_harden_sovereign_decisions':'69ef485a0a2c006c35727111935761a0e0106630b4fbd21b341cd55b09c0b697',
 '0026_global_user_memory_scope':'37f399b203d757280d8e9ae247eb6543154bb472f2102ae83245cf4b1d7bb043',
 '0027_complete_bitemporality':'c0335ef7d6b5f97c577cf49564375a0120fe7b5f97557ad5fc85cf1853a1609c',
 '0028_economic_memory':'6bbd7623c8b46409287f2897f634b9ffd4035694920d1250d041ee7ab71414f3',
 '0029_operational_memory_b2':'af5d4b7823ddacc43a7afad68d1b58c2c98047d1bb93fde2d9e35bacc034272e',
 '0030_input_guard_v2':'461ed916ec65a6f2d224caa0ca7bb6a9264dbf881c2941e5093ed3ddd328be9b',
 '0030z_recovery_equivalent_historical_0031':'2ff124a7d74e8625872f5d37fdd9e7b596ad5ce53b72bcb0488886103e3cff43',
 '0032_ui_governance_p0_ui_b':'21354d58d8a290e56fc3dafeaa883a618c934c9415d51aa95782533c787d6626',
 '0032z_recovery_equivalent_historical_0033':'126511d17d6f8bd479952874e4d1db52c6636193b44b258b8188475e59b198b1',
 '0034_sync_ui_governance_m12':'8ad033532b8c2522a952f12ed4cb7b0aa6dff79855e646974030ac626039ba22',
 '0035_legal_erasure_backup_governance':'ba8b50a52d7f3361aca5c06a80504bd43813e18563f933b002ec9a31ff79f030',
 '0036_legal_erasure_extended_redaction':'a8ad599e41fcbde9d5959c943e374d2ea8a93bdc289bba4903db76f80e3180f8',
 '0037_fix_legal_erasure_and_gate_p18':'3ce96c523c45af91fef017e6b6aa3edd9cef21a8cf72692bebc1039109d91e77',
 '0038_p18_gate_and_mutation_hardening':'8759ea9bc8425e908681c6340b111bd2aab7cd93bee9b539aacc58fc27fdbbf6',
 '0039_restore_order_hardening':'91d80246769756f99e98c280387941627a29df7b9b7aece7946a185141a44349',
}

def test_applied_migration_bytes_are_immutable() -> None:
    mismatches=[]
    for version,expected in EXPECTED.items():
        path=ROOT/'migrations'/f'{version}.sql'
        actual=hashlib.sha256(path.read_bytes()).hexdigest()
        if actual!=expected:
            mismatches.append((version,expected,actual))
    assert mismatches==[]
