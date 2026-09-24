from memory_permanent.api import app
from memory_permanent.conversation_ingestion_api import ConversationTurnRequest
from memory_permanent.session_rotation_api import (
    ExternalConversationCaptureRequest,
    ExternalConversationMessage,
)


def test_ingestion_routes_are_public():
    paths=set(app.openapi()['paths'])
    assert '/v1/conversation-ingestion/turn' in paths
    assert '/v1/conversation-ingestion/retry' in paths
    assert '/v1/conversation-ingestion/pending' in paths
    assert '/v1/conversation-ingestion/health' in paths


def test_write_through_source_is_not_learning():
    turn=ConversationTurnRequest(external_session_ref='/c/test',role='user',text='hello',message_id='m1',ordinal=0)
    assert turn.capture_source == 'CONVERSATION_RUNTIME'
    assert 'LEARNING' not in turn.capture_source


def test_bulk_import_source_is_not_learning_by_default():
    req=ExternalConversationCaptureRequest(provider='chatgpt',external_session_ref='/c/test',objective='import',messages=[ExternalConversationMessage(role='user',text='hello',message_id='m1')])
    assert req.capture_source == 'EXTERNAL_IMPORT'
    assert 'LEARNING' not in req.capture_source
