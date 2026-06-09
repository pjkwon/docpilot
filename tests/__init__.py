# 이 파일이 비어있어도 삭제하면 안 됨.
# tests/ 를 Python 패키지로 만들어서 테스트 파일 간 import가 가능하게 한다.
# 예: test_search.py → from tests.mocks.db_mock import mock_db_session
#     test_mapping.py → from tests.mocks.llm_mock import MockMapper
# __init__.py 없으면 "tests.mocks.xxx" 경로가 성립하지 않아 ImportError 발생.
