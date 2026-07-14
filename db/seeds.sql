-- 카테고리 기본 데이터 (14개 대분류)
INSERT INTO categories (name) VALUES
    ('접근통제'),
    ('암호화'),
    ('로그관리 및 모니터링'),
    ('물리적 보안'),
    ('개인정보보호'),
    ('침해사고 대응'),
    ('정보자산 관리'),
    ('인적 보안'),
    ('외부자 및 공급망 보안'),
    ('취약점 및 패치 관리'),
    ('시스템 개발 보안'),
    ('업무 연속성'),
    ('위험 관리'),
    ('보안 정책 및 조직')
ON CONFLICT (name) DO NOTHING;

-- 기본 조직 (프론트엔드 DEFAULT_ORG_ID와 동일)
INSERT INTO organizations (id, name) VALUES
    ('00000000-0000-0000-0000-000000000001', 'Default Organization')
ON CONFLICT (id) DO NOTHING;
