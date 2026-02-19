from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL / SUPABASE_KEY 환경변수가 설정되지 않았습니다.")
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def fetch_all_draws() -> list[dict]:
    """lotto_draws 테이블의 모든 데이터를 반환한다."""
    client = get_client()
    result = client.table("lotto_draws").select("*").order("round", desc=True).execute()
    return result.data or []


def fetch_recent_draws(limit: int = 10) -> list[dict]:
    """최근 N회차 데이터를 반환한다."""
    client = get_client()
    result = (
        client.table("lotto_draws")
        .select("*")
        .order("round", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def fetch_draws_after(round_num: int) -> list[dict]:
    """특정 회차 이후의 데이터를 반환한다 (증분 업데이트용)."""
    client = get_client()
    result = (
        client.table("lotto_draws")
        .select("*")
        .gt("round", round_num)
        .order("round")
        .execute()
    )
    return result.data or []


def fetch_missing_counts(target_round: int) -> dict:
    """number_features_by_round 테이블에서 target_round 직전 회차의 missing_count 조회.
    반환: {번호(int): missing_count(int)}
    """
    client = get_client()
    try:
        # target_round 바로 이전 회차 데이터 조회
        result = (
            client.table("number_features_by_round")
            .select("number, missing_count")
            .eq("round", target_round - 1)
            .execute()
        )
        if result.data:
            return {int(row["number"]): int(row["missing_count"]) for row in result.data}
    except Exception as e:
        print(f"[missing_counts] Supabase 조회 실패: {e}")
    return {}


# Export for direct usage
try:
    supabase = get_client()
except Exception:
    supabase = None
