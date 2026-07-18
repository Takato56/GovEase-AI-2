import asyncio
import json
import os
import re
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


SCRAPE_ARTIFACT_PATTERNS = [
    "Thủ tục hành chính liên quanKhông",
    "Cách Thức Thực HiệnHình thức",
    "Cách thức thực hiệnHình thức",
    "Căn cứ pháp lýTên văn bản",
    "Cơ quan phối hợpBộ",
    "CSDLQGVDC.1 bản",
    "nước ngoàiThông tư",
]

SCRAPE_ARTIFACT_REGEXES = [
    re.compile(r"thẻ\s{2,}Căn cước", re.IGNORECASE),
    re.compile(r"cho phép\s{2,}Cơ quan", re.IGNORECASE),
    re.compile(r"\b\d{1,3}\s*VNĐ\b", re.IGNORECASE),
]


def clean_text(text):
    text = (text or "").replace("\xa0", " ")
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def clean_multiline_text(text):
    lines = [clean_text(line) for line in (text or "").splitlines()]
    return "\n".join(line for line in lines if line)


def node_text(node, separator="\n"):
    if not node:
        return ""
    return clean_multiline_text(node.get_text(separator, strip=True))


def find_row_value(row, names):
    normalized_names = [name.lower() for name in names]
    for key, value in row.items():
        key_lower = key.lower()
        if any(name in key_lower for name in normalized_names):
            return value
    return ""


def split_primary_detail(text):
    lines = clean_multiline_text(text).splitlines()
    if not lines:
        return "", ""
    return lines[0], "\n".join(lines[1:]).strip()


def normalize_fee_value(fee):
    fee = clean_text(fee)
    match = re.fullmatch(r"(\d{1,3})\s*VNĐ", fee, flags=re.IGNORECASE)
    if match:
        # Consular-fee pages sometimes render USD-denominated fees with a VNĐ suffix.
        return f"{match.group(1)} USD"
    return fee


def normalize_output_text(text):
    return clean_multiline_text(text)


def normalize_dataset_item(item):
    for field in ("instruction", "context", "response"):
        if field in item:
            item[field] = normalize_output_text(item[field])
    return item


def has_scrape_artifacts(item):
    blob = "\n".join(
        str(item.get(field, "")) for field in ("instruction", "context", "response")
    )
    return any(pattern in blob for pattern in SCRAPE_ARTIFACT_PATTERNS) or any(
        regex.search(blob) for regex in SCRAPE_ARTIFACT_REGEXES
    )


def should_refresh_existing_item(existing_item, new_item):
    if has_scrape_artifacts(existing_item):
        return True

    return (
        existing_item.get("context") != new_item.get("context")
        or existing_item.get("response") != new_item.get("response")
        or not existing_item.get("source_url")
    )


def parse_table_rows(table):
    headers = [node_text(th, " ") for th in table.find_all("th")]
    rows = []

    for tr in table.select("tbody tr"):
        cells = [node_text(td) for td in tr.find_all("td")]
        if not any(cells):
            continue

        row = {}
        for index, cell in enumerate(cells):
            header = headers[index] if index < len(headers) and headers[index] else f"Cột {index + 1}"
            row[header] = cell
        rows.append(row)

    return rows


def format_submission_methods(rows):
    blocks = []
    for row in rows:
        method = find_row_value(row, ["Hình thức nộp", "Hình thức"]) or "Hình thức nộp"
        time = find_row_value(row, ["Thời gian", "Thời hạn"])
        fee = find_row_value(row, ["Phí, lệ phí", "Lệ phí", "Phí"])
        description = find_row_value(row, ["Mô tả", "Ghi chú"])
        fee_value, fee_note = split_primary_detail(fee)
        fee_value = normalize_fee_value(fee_value)

        lines = [f"**{method}:**"]
        if time:
            lines.append(f"* Thời gian: {time}")
        if fee_value:
            lines.append(f"* Lệ phí: {fee_value}")
        if fee_note:
            lines.append(f"* Ghi chú lệ phí: {fee_note}")
        if description:
            lines.append(f"* Mô tả: {description}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def format_legal_basis(rows):
    lines = []
    for row in rows:
        name = find_row_value(row, ["Tên văn bản pháp lý", "Văn bản", "Tên văn bản"])
        code = find_row_value(row, ["Mã văn bản", "Số ký hiệu", "Mã"])

        if name and code:
            lines.append(f"* {name} (Mã văn bản: {code})")
        elif name:
            lines.append(f"* {name}")
        elif code:
            lines.append(f"* {code}")

    return "\n".join(lines)


def format_generic_table(rows):
    lines = []
    for row in rows:
        parts = [f"{key}: {value}" for key, value in row.items() if value]
        if parts:
            lines.append(f"* {'; '.join(parts)}")
    return "\n".join(lines)


def extract_general_info(main_content):
    info = {}

    for row in main_content.find_all("div"):
        classes = row.get("class") or []
        if not {"flex", "flex-col", "md:flex-row", "border-gray-300"}.issubset(set(classes)):
            continue

        cells = [child for child in row.find_all("div", recursive=False)]
        if len(cells) < 2:
            continue

        key = node_text(cells[0], " ")
        value = node_text(cells[1], " ")
        if key and value:
            info[key] = value

    return info


def match_section_title(title, keywords):
    title_lower = title.lower()
    for keyword in keywords:
        if keyword.lower() in title_lower:
            return keyword
    return ""


def extract_heading_sections(main_content, keywords):
    sections = {}
    table_rows_by_section = {}

    for heading in main_content.find_all("h4"):
        title = node_text(heading, " ")
        section_name = match_section_title(title, keywords)
        if not section_name:
            continue

        container = heading.parent
        tables = container.find_all("table") if container else []
        if tables:
            section_rows = []
            formatted_tables = []
            for table in tables:
                rows = parse_table_rows(table)
                if not rows:
                    continue

                section_rows.extend(rows)
                if "Cách thức" in section_name:
                    formatted_tables.append(format_submission_methods(rows))
                elif "Căn cứ pháp lý" in section_name:
                    formatted_tables.append(format_legal_basis(rows))
                else:
                    formatted_tables.append(format_generic_table(rows))

            content = "\n\n".join(table for table in formatted_tables if table).strip()
            if content:
                sections[section_name] = content
                table_rows_by_section[section_name] = section_rows
            continue

        body_parts = []
        for sibling in heading.find_next_siblings():
            if sibling.name == "h4":
                break
            text = node_text(sibling)
            if text and text.lower() != "không có thông tin":
                body_parts.append(text)

        content = "\n".join(body_parts).strip()
        if content:
            sections[section_name] = content

    return sections, table_rows_by_section


def is_free_fee(fee):
    return "miễn phí" in fee.lower() or fee.strip() in {"0", "0 đồng", "0đ"}


def build_fee_response(ten_thu_tuc, method, fee, doi_tuong):
    method_part = f" khi nộp {method.lower()}" if method else ""
    actor = "công dân" if "công dân" in doi_tuong.lower() else "người thực hiện"
    subject = f"của {actor}"

    if is_free_fee(fee):
        return (
            f"Lệ phí của thủ tục '{ten_thu_tuc}' {subject}{method_part} là miễn phí; "
            f"{actor} không cần nộp phí/lệ phí cho hình thức này."
        )

    return f"Lệ phí của thủ tục '{ten_thu_tuc}' {subject}{method_part} là {fee}."


async def scrape_to_advanced_json(
    browser, url, output_filename="dataset_dvc_augmented.json"
):
    """Giữ nguyên 100% logic augmentation của ông, chỉ fix lõi đợi Javascript."""
    print(f"[*] Đang kết nối và tải trang: {url} ...")

    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    page = await context.new_page()

    try:
        # 1. ĐIỀU HƯỚNG VÀ ĐỢI JAVASCRIPT RENDER
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        source_url = page.url or url

        # Chờ chính xác class chứa nội dung của cổng DVC xuất hiện (fix lỗi selector chứa dấu hai chấm)
        target_selector = "div.mx-auto.pb-0.lg\\:pb-4"
        await page.wait_for_selector(target_selector, timeout=15000)
        await page.wait_for_timeout(1000)  # Giãn cách 1s cho chắc chắn

        html_content = await page.content()
        soup = BeautifulSoup(html_content, "html.parser")

        # Giới hạn soup lại đúng vùng chứa dữ liệu để tránh cào trúng sidebar/footer
        main_content = soup.find("div", class_="mx-auto pb-0 lg:pb-4")
        if not main_content:
            main_content = soup  # Fallback nếu cấu trúc trang có thay đổi nhẹ

        # --- GIỮ NGUYÊN HOÀN TOÀN LOGIC BÓC TÁCH CỦA ÔNG ---
        title_node = main_content.find("h3") or main_content.find("h1")
        ten_thu_tuc = (
            title_node.text.strip() if title_node else "Thủ tục hành chính"
        )

        thong_tin_chung = extract_general_info(main_content)
        if not thong_tin_chung:
            for item in main_content.select(".form-group, .info-item"):
                if item.find_parent("table"):
                    continue

                text = node_text(item, " ")
                if ":" in text:
                    parts = text.split(":", 1)
                    key = clean_text(parts[0])
                    val = clean_text(parts[1])
                    if key and val and len(key) < 50:
                        thong_tin_chung[key] = val

        noi_dung_chi_tiet = {}
        current_section = "Nội dung khác"

        keywords = [
            "Trình tự thực hiện",
            "Cách thức thực hiện",
            "Thành phần hồ sơ",
            "Thời hạn giải quyết",
            "Đối tượng thực hiện",
            "Cơ quan thực hiện",
            "Kết quả thực hiện",
            "Lệ phí",
            "Yêu cầu - điều kiện",
            "Yêu cầu, điều kiện thực hiện",
            "Căn cứ pháp lý",
            "Kết quả xử lý",
        ]

        for element in main_content.find_all(
            ["h4", "h5", "b", "strong", "p", "div"]
        ):
            text = node_text(element, " ")
            if not text:
                continue

            is_header = (
                element.name in {"h4", "h5", "b", "strong"}
                and any(kw.lower() in text.lower() for kw in keywords)
                and len(text) < 100
            )

            if is_header:
                for kw in keywords:
                    if kw.lower() in text.lower():
                        current_section = kw
                        break
                if current_section not in noi_dung_chi_tiet:
                    noi_dung_chi_tiet[current_section] = []
            else:
                if (
                    current_section in noi_dung_chi_tiet
                    and text not in noi_dung_chi_tiet[current_section]
                ):
                    if element.name == "div" and element.find(
                        ["div", "table", "h4", "h5"], recursive=False
                    ):
                        continue
                    if len(text) > 15 and text not in keywords:
                        noi_dung_chi_tiet[current_section].append(text)

        for section in noi_dung_chi_tiet:
            noi_dung_chi_tiet[section] = "\n".join(
                noi_dung_chi_tiet[section]
            ).strip()

        structured_sections, table_rows_by_section = extract_heading_sections(
            main_content, keywords
        )
        noi_dung_chi_tiet.update(structured_sections)

        # --- LOGIC DATA AUGMENTATION CỦA ÔNG ---
        new_dataset = []

        # DẠNG 1: THÔNG TIN TỔNG QUAN
        context_tong_quan = f"Thủ tục: {ten_thu_tuc}.\n" + "\n".join(
            [f"- {k}: {v}" for k, v in thong_tin_chung.items()]
        )
        response_tong_quan = f"Dưới đây là thông tin chi tiết về thủ tục '{ten_thu_tuc}':\n" + "\n".join(
            [f"+ {k}: {v}" for k, v in thong_tin_chung.items()]
        )

        cau_hoi_tong_quan = [
            f"Thủ tục {ten_thu_tuc} có thông tin như thế nào?",
            f"Cho mình xin thông tin cơ bản của thủ tục {ten_thu_tuc} với.",
            f"Mã thủ tục và cơ quan thực hiện của {ten_thu_tuc} là gì?",
            f"Giải đáp giúp tôi về thủ tục hành chính: {ten_thu_tuc}",
            f"Tóm tắt thông tin pháp lý của {ten_thu_tuc}.",
        ]
        for q in cau_hoi_tong_quan:
            new_dataset.append(
                {
                    "instruction": q,
                    "context": context_tong_quan,
                    "response": response_tong_quan,
                    "source_url": source_url,
                }
            )

        # DẠNG 2: CHI TIẾT THEO MỤC
        for muc, noi_dung in noi_dung_chi_tiet.items():
            if len(noi_dung) < 20:
                continue

            context_muc = f"Thủ tục: {ten_thu_tuc}. Danh mục: {muc}."
            templates = []

            if "Hồ sơ" in muc:
                templates = [
                    f"Làm thủ tục {ten_thu_tuc} thì cần chuẩn bị những giấy tờ gì?",
                    f"Thành phần hồ sơ của thủ tục {ten_thu_tuc} gồm những gì vậy admin?",
                    f"List giấy tờ bắt buộc phải nộp khi thực hiện {ten_thu_tuc}.",
                    f"Tôi muốn nộp hồ sơ {ten_thu_tuc}, hướng dẫn tôi chuẩn bị tài liệu với.",
                    f"Hồ sơ {ten_thu_tuc} cần những loại văn bản nào?",
                ]
            elif "Trình tự" in muc:
                templates = [
                    f"Các bước thực hiện thủ tục {ten_thu_tuc} như thế nào?",
                    f"Trình tự các bước từ A đến Z để làm {ten_thu_tuc}.",
                    f"Cho mình hỏi quy trình các bước giải quyết thủ tục {ten_thu_tuc}.",
                    f"Quy trình xử lý của thủ tục {ten_thu_tuc} gồm mấy bước?",
                    f"Làm sao để hoàn thành thủ tục {ten_thu_tuc}? Hướng dẫn các bước cho tôi.",
                ]
            elif "Cách thức" in muc:
                templates = [
                    f"Nộp thủ tục {ten_thu_tuc} ở đâu và bằng cách nào?",
                    f"Có thể nộp hồ sơ {ten_thu_tuc} online hay phải đến trực tiếp?",
                    f"Phương thức tiếp nhận và trả kết quả của {ten_thu_tuc} là gì?",
                    f"Cách thức nộp hồ sơ của thủ tục {ten_thu_tuc}.",
                ]
            elif "Lệ phí" in muc or "Phí" in muc:
                templates = [
                    f"Làm thủ tục {ten_thu_tuc} có tốn tiền không và hết bao nhiêu?",
                    f"Mức lệ phí áp dụng cho thủ tục {ten_thu_tuc} là bao nhiêu vậy?",
                    f"Chi phí và giá tiền khi đi làm thủ tục {ten_thu_tuc}.",
                    f"Nộp {ten_thu_tuc} có mất phí không?",
                ]
            elif "Căn cứ pháp lý" in muc:
                templates = [
                    f"Căn cứ pháp lý của thủ tục {ten_thu_tuc} gồm những văn bản nào?",
                    f"Thủ tục {ten_thu_tuc} được quy định bởi văn bản pháp lý nào?",
                    f"Cho tôi danh sách văn bản pháp luật làm căn cứ cho thủ tục {ten_thu_tuc}.",
                    f"Cơ sở pháp lý khi thực hiện {ten_thu_tuc} là gì?",
                ]
            elif "Thời hạn" in muc:
                templates = [
                    f"Sau bao lâu thì nhận được kết quả thủ tục {ten_thu_tuc}?",
                    f"Thời gian giải quyết hồ sơ {ten_thu_tuc} quy định là mấy ngày?",
                    f"Làm {ten_thu_tuc} mất bao lâu thì xong hả bạn?",
                    f"Thời hạn xử lý tối đa của thủ tục {ten_thu_tuc}.",
                ]
            else:
                templates = [
                    f"Quy định về {muc.lower()} của thủ tục {ten_thu_tuc} là gì?",
                    f"Cho mình biết chi tiết về {muc.lower()} khi làm {ten_thu_tuc}.",
                    f"Tìm hiểu thông tin về {muc.lower()} liên quan đến {ten_thu_tuc}.",
                    f"Vấn đề {muc.lower()} của thủ tục {ten_thu_tuc} được quy định như thế nào?",
                ]

            for q in templates:
                if "Căn cứ pháp lý" in muc:
                    response = f"Căn cứ pháp lý của thủ tục '{ten_thu_tuc}' gồm:\n{noi_dung}"
                else:
                    response = f"Về vấn đề '{muc.lower()}' của thủ tục '{ten_thu_tuc}', quy định chi tiết như sau:\n{noi_dung}"

                new_dataset.append(
                    {
                        "instruction": q,
                        "context": context_muc,
                        "response": response,
                        "source_url": source_url,
                    }
                )

        # DẠNG 3: LỆ PHÍ THEO TỪNG HÌNH THỨC NỘP
        doi_tuong = thong_tin_chung.get("Đối tượng thực hiện", "")
        fee_rows = []
        for rows in table_rows_by_section.values():
            for row in rows:
                fee = find_row_value(row, ["Phí, lệ phí", "Lệ phí", "Phí"])
                if fee:
                    fee_rows.append(row)

        for row in fee_rows:
            method = find_row_value(row, ["Hình thức nộp", "Hình thức"])
            fee = find_row_value(row, ["Phí, lệ phí", "Lệ phí", "Phí"])
            time = find_row_value(row, ["Thời gian", "Thời hạn"])
            fee_value, fee_note = split_primary_detail(fee)
            fee_value = normalize_fee_value(fee_value)

            method_lower = method.lower() if method else "hình thức này"
            context_phi = (
                f"Thủ tục: {ten_thu_tuc}.\n"
                f"Hình thức nộp: {method or 'Không nêu rõ'}.\n"
                f"Lệ phí: {fee_value or fee}"
            )
            if time:
                context_phi += f"\nThời gian giải quyết: {time}."
            if fee_note:
                context_phi += f"\nGhi chú lệ phí: {fee_note}."

            response_phi = build_fee_response(
                ten_thu_tuc, method, fee_value or fee, doi_tuong
            )
            fee_templates = [
                f"Mức lệ phí của thủ tục {ten_thu_tuc} khi nộp {method_lower} là bao nhiêu?",
                f"Nộp {method_lower} thủ tục {ten_thu_tuc} có mất phí không?",
                f"Chi phí khi thực hiện {ten_thu_tuc} bằng hình thức {method_lower} là bao nhiêu?",
            ]

            for q in fee_templates:
                new_dataset.append(
                    {
                        "instruction": q,
                        "context": context_phi,
                        "response": response_phi,
                        "source_url": source_url,
                    }
                )

        new_dataset = [normalize_dataset_item(item) for item in new_dataset]

        # --- LOGIC GHI ĐÈ / MERGE CHỐNG TRÙNG FILE CŨ CỦA ÔNG ---
        final_dataset = []
        existing_questions = set()
        existing_by_question = {}
        removed_artifact_count = 0
        updated_count = 0

        if os.path.exists(output_filename):
            try:
                with open(output_filename, "r", encoding="utf-8") as f:
                    final_dataset = json.load(f)
                    if not isinstance(final_dataset, list):
                        final_dataset = []
                    original_count = len(final_dataset)
                    final_dataset = [
                        item
                        for item in final_dataset
                        if not has_scrape_artifacts(item)
                    ]
                    removed_artifact_count = original_count - len(final_dataset)
                    existing_questions = {
                        item["instruction"]
                        for item in final_dataset
                        if "instruction" in item
                    }
                    existing_by_question = {
                        item["instruction"]: item
                        for item in final_dataset
                        if "instruction" in item
                    }
                print(
                    f"[*] Đã tìm thấy file cũ. Đang giữ lại {len(final_dataset)} mẫu cũ..."
                )
                if removed_artifact_count:
                    print(
                        f"[*] Đã loại {removed_artifact_count} mẫu bị dính text DOM/bảng cũ."
                    )
            except Exception as e:
                print(f"[!] File cũ lỗi hoặc trống, tạo mới: {e}")
                final_dataset = []

        added_count = 0
        for item in new_dataset:
            if item["instruction"] not in existing_questions:
                final_dataset.append(item)
                existing_questions.add(item["instruction"])
                existing_by_question[item["instruction"]] = item
                added_count += 1
            else:
                existing_item = existing_by_question[item["instruction"]]
                if should_refresh_existing_item(existing_item, item):
                    existing_item.update(item)
                    updated_count += 1

        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(final_dataset, f, ensure_ascii=False, indent=4)

        print(
            f"[+] [{url}] -> Thêm thành công: {added_count} câu hỏi, cập nhật: {updated_count}."
        )

    except Exception as e:
        print(f"[!] Có lỗi xảy ra tại URL {url}: {e}")
    finally:
        await context.close()


async def main_batch_executor(urls, batch_size=4, delay=3):
    """Hàm chia loạt (Batching) chạy async cho nhiều URL cùng một lúc."""
    output_file = "dataset_dvc_augmented.json"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for i in range(0, len(urls), batch_size):
            batch = urls[i : i + batch_size]
            print(
                f"\n==> ĐANG CHẠY BATCH {i//batch_size + 1} (Gồm {len(batch)} URLs)..."
            )

            # Chạy đồng thời các URL trong cùng một batch bằng asyncio.gather
            tasks = [
                scrape_to_advanced_json(browser, url, output_file)
                for url in batch
            ]
            await asyncio.gather(*tasks)

            if i + batch_size < len(urls):
                print(f"Nghỉ {delay}s để tránh quá tải/block...")
                await asyncio.sleep(delay)

        await browser.close()
    print("\n[DONE] Đã hoàn thành toàn bộ danh sách cào!")


# --- THỰC THI CHẠY THỬ ---
if __name__ == "__main__":
    list_urls = [
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf9-f979-762a-ae2e-e7a98afcd758",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf9-f1d6-739a-b9b3-59fd5f1263fb",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf9-e9f6-75df-b941-0b375e40850e",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf9-e9cc-71bb-bce1-c01b68788909",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf9-e9b9-754f-b246-98f868065e48",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf7-bd72-72af-ac7d-f47e6bd3ae36",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf7-bd6e-77de-83d1-c3c4f8bdb14e",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf7-bd61-75c7-8c55-3ba0e1135463",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf7-7f06-7316-a1c8-3255e08fe2f5",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf7-7efc-7491-9ac8-527fe53522e4",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf7-770b-734d-b7fb-5e1995f194f4",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf7-6f41-722b-876f-5f62759452d4",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf7-6f34-76df-9bd6-78fe90462e4b",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf7-6f17-7561-bd4d-811d3c432237",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf7-6762-77ee-9a0c-965773ce7afe",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf7-6755-734f-ad71-21d637733708",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf7-5fae-761b-9c8e-694371482303",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf7-5f61-72e9-acd7-30da53e18cc9",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf7-57ba-70d3-8771-4bbb754b4b31",
  "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/019d2bf7-4fc4-7716-bab8-167242b3fcda"
]

    # Thực thi chạy bất đồng bộ theo batch (Mỗi lần 4 trang)
    asyncio.run(main_batch_executor(list_urls, batch_size=4, delay=3))
