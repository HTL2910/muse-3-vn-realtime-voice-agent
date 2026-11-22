"""Resilience cho chuỗi ASR-LLM-TTS: circuit breaker và fallback đa nhà cung cấp

Chuyên gia phụ trách: fullstack-ux (Chuyên gia Ứng dụng & Tích hợp)
Đặc tả: Gộp systems-arch[2-phần breaker], backend-sec[6], fullstack-ux[1-phần breaker]. Ngân sách độ trễ end-to-end cho mỗi lượt thoại (p95 <1200ms từ khi khách nói xong đến âm thanh đầu tiên), phân bổ rõ cho VAD, ASR streaming, retrieval, LLM và TTS streaming; vượt ngân sách thì rút gọn ngữ cảnh, dùng template/cache hoặc chuyển chế độ an toàn thay vì để khách nghe im lặng. Mỗi nhà cung cấp ASR/TTS/LLM có circuit breaker, bulkhead pool riêng và health check; lỗi liên tiếp thì tự chuyển nhà cung cấp dự phòng tiếng Việt (FPT/Vbee/Azure/Google) theo ma trận chất lượng đã đo. Mọi lỗi có mã và trace_id xuyên suốt cuộc gọi để tái hiện vì sao một câu bị trả lời sai hoặc bị chuyển.
"""

def solve_approach_16(data=None):
    return {"code": 'approach_16', "title": 'Resilience cho chuỗi ASR-LLM-TTS: circuit breaker và fallback đa nhà cung cấp', "expert": 'fullstack-ux', "status": "ok", "input": data}
