from db.supabase_client import get_client
import traceback

def get_all_draws() -> list:
    """
    모든 로또 회차 데이터를 가져옵니다.
    (API 호출 최소화를 위해 필요한 필드만 선택)
    """
    try:
        supabase = get_client()
        
        # drw_no_date는 날짜 계산 등에 필요할 수 있음
        response = supabase.table("lotto_draws") \
            .select("round, drw_no_date, drwt_no1, drwt_no2, drwt_no3, drwt_no4, drwt_no5, drwt_no6, bnus_no") \
            .order("round", desc=False) \
            .execute()
        
        # response가 postgrest.base_request_builder.APIResponse 객체일 수 있음
        if hasattr(response, 'data'):
            return response.data
        return response
        
    except Exception as e:
        print(f"[FAIL] Supabase Fetch Error: {e}")
        # traceback.print_exc()
        return []
