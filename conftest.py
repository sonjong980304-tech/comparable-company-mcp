"""프로젝트 루트를 sys.path 에 올려 테스트에서 최상위 모듈을 임포트할 수 있게 한다."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
