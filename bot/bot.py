import os
import re
import json
import base64
import html as html_lib
from datetime import datetime, timezone, timedelta
from io import BytesIO

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_ID = int(os.environ["TELEGRAM_ADMIN_ID"])
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_OWNER = os.getenv("GITHUB_OWNER", "rahmatjepara")
GITHUB_REPO = os.getenv("GITHUB_REPO", "rahmat-jepara")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
STATUS_PATH = os.getenv("STATUS_PATH", "products-status.json")
PRODUCT_HTML_PATH = os.getenv("PRODUCT_HTML_PATH", "produk.html")
IMAGE_FOLDER = os.getenv("IMAGE_FOLDER", "images")
WARRANTY_PATH = os.getenv("WARRANTY_PATH", "warranties.json")

API_ROOT = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "X-GitHub-Api-Version": "2022-11-28",
}
CODE_RE = re.compile(r"^jt(\d{1,3})$", re.I)
NEW_PRODUCT_DRAFTS = {}
EDIT_PRODUCT_DRAFTS = {}
PHOTO_REPLACE_DRAFTS = {}
DELETE_PRODUCT_DRAFTS = {}
WARRANTY_DRAFTS = {}


def is_admin(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id == ADMIN_ID)


async def reject_if_not_admin(update: Update) -> bool:
    if is_admin(update):
        return False
    if update.effective_message:
        await update.effective_message.reply_text("⛔ Bot ini khusus admin Rahmat Jepara.")
    return True


def gh_get_json(path):
    r = requests.get(
        f"{API_ROOT}/contents/{path}", headers=HEADERS,
        params={"ref": GITHUB_BRANCH}, timeout=30
    )
    r.raise_for_status()
    payload = r.json()
    raw = base64.b64decode(payload["content"])
    return json.loads(raw.decode("utf-8")), payload["sha"]


def gh_get_text(path):
    r = requests.get(
        f"{API_ROOT}/contents/{path}", headers=HEADERS,
        params={"ref": GITHUB_BRANCH}, timeout=30
    )
    r.raise_for_status()
    payload = r.json()
    raw = base64.b64decode(payload["content"])
    return raw.decode("utf-8"), payload["sha"]


def gh_get_branch_head():
    r = requests.get(f"{API_ROOT}/git/ref/heads/{GITHUB_BRANCH}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()["object"]["sha"]


def gh_get_commit(commit_sha):
    r = requests.get(f"{API_ROOT}/git/commits/{commit_sha}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def gh_create_blob(content_bytes):
    r = requests.post(
        f"{API_ROOT}/git/blobs", headers=HEADERS,
        json={"content": base64.b64encode(content_bytes).decode("ascii"), "encoding": "base64"},
        timeout=30
    )
    r.raise_for_status()
    return r.json()["sha"]


def gh_atomic_commit(file_map, message):
    """Create one Git commit containing all changed files."""
    head_sha = gh_get_branch_head()
    head_commit = gh_get_commit(head_sha)
    base_tree_sha = head_commit["tree"]["sha"]

    entries = []
    for path, content in file_map.items():
        entries.append({
            "path": path,
            "mode": "100644",
            "type": "blob",
            "sha": None if content is None else gh_create_blob(content),
        })

    r = requests.post(
        f"{API_ROOT}/git/trees", headers=HEADERS,
        json={"base_tree": base_tree_sha, "tree": entries}, timeout=30
    )
    r.raise_for_status()
    tree_sha = r.json()["sha"]

    r = requests.post(
        f"{API_ROOT}/git/commits", headers=HEADERS,
        json={"message": message, "tree": tree_sha, "parents": [head_sha]}, timeout=30
    )
    r.raise_for_status()
    new_commit_sha = r.json()["sha"]

    r = requests.patch(
        f"{API_ROOT}/git/refs/heads/{GITHUB_BRANCH}", headers=HEADERS,
        json={"sha": new_commit_sha, "force": False}, timeout=30
    )
    r.raise_for_status()
    return new_commit_sha


def github_get_inventory():
    return gh_get_json(STATUS_PATH)


def github_save_inventory(data, sha, message):
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    encoded = base64.b64encode(
        json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("ascii")
    r = requests.put(
        f"{API_ROOT}/contents/{STATUS_PATH}", headers=HEADERS,
        json={"message": message, "content": encoded, "sha": sha, "branch": GITHUB_BRANCH},
        timeout=30
    )
    r.raise_for_status()
    return r.json()


def github_get_warranties():
    r = requests.get(
        f"{API_ROOT}/contents/{WARRANTY_PATH}", headers=HEADERS,
        params={"ref": GITHUB_BRANCH}, timeout=30
    )
    if r.status_code == 404:
        return {"updated_at": None, "warranties": {}}, None
    r.raise_for_status()
    payload = r.json()
    raw = base64.b64decode(payload["content"])
    return json.loads(raw.decode("utf-8")), payload["sha"]


def github_save_warranties(data, sha, message):
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    encoded = base64.b64encode(
        json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("ascii")
    body = {
        "message": message,
        "content": encoded,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        body["sha"] = sha
    r = requests.put(
        f"{API_ROOT}/contents/{WARRANTY_PATH}",
        headers=HEADERS, json=body, timeout=30
    )
    r.raise_for_status()
    return r.json()


JAKARTA_TZ = timezone(timedelta(hours=7))
WARRANTY_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{3,39}$")


def normalize_warranty_code(raw: str) -> str:
    code = (raw or "").strip().upper()
    if not WARRANTY_CODE_RE.fullmatch(code):
        raise ValueError(
            "Kode garansi harus 4-40 karakter dan hanya boleh berisi huruf, angka, - atau _."
        )
    return code


def warranty_dates():
    start = datetime.now(JAKARTA_TZ).date()
    try:
        expires = start.replace(year=start.year + 1)
    except ValueError:
        expires = start.replace(year=start.year + 1, day=28)
    return start, expires


def warranty_status(record):
    try:
        expires = datetime.strptime(record.get("expires_at", ""), "%Y-%m-%d").date()
    except ValueError:
        return "INVALID"
    today = datetime.now(JAKARTA_TZ).date()
    if record.get("cancelled", False):
        return "CANCELLED"
    return "ACTIVE" if today <= expires else "EXPIRED"


def format_warranty(code, record):
    status = warranty_status(record)
    icon = {"ACTIVE": "✅", "EXPIRED": "⚠️", "CANCELLED": "⛔", "INVALID": "❌"}.get(status, "❓")
    return (
        f"{icon} {code} | {record.get('product_code', '-')} | {status} | "
        f"{record.get('activated_at', '-')} → {record.get('expires_at', '-')}"
    )


def normalize_code(raw: str) -> str:
    m = CODE_RE.match(raw.strip())
    if not m:
        raise ValueError("Kode produk tidak valid.")
    return f"JT{int(m.group(1)):03d}"


def get_product(data, code):
    products = data.setdefault("products", {})
    if code not in products:
        raise KeyError(f"{code} belum ada di products-status.json.")
    return products[code]


def status_icon(stock):
    return "🟢" if stock > 0 else "🔴"


def status_text(stock):
    return "AVAILABLE" if stock > 0 else "SOLD OUT"


def format_product(code, product):
    stock = int(product.get("stock", 0))
    return f"{status_icon(stock)} {code} | {product.get('koleksi', code)} | Stok: {stock} | {status_text(stock)}"


def next_product_number(data):
    nums = []
    for code in data.get("products", {}):
        m = re.match(r"^JT(\d+)$", code, re.I)
        if m:
            nums.append(int(m.group(1)))
    return max(nums) + 1 if nums else 1


def normalize_category(value):
    raw = value.strip().lower()
    aliases = {
        "ruang tamu": "ruang-tamu", "ruang-tamu": "ruang-tamu", "tamu": "ruang-tamu",
        "ruang makan": "ruang-makan", "ruang-makan": "ruang-makan", "makan": "ruang-makan",
        "kamar tidur": "kamar-tidur", "kamar-tidur": "kamar-tidur", "kamar": "kamar-tidur",
        "koleksi lainnya": "koleksi-lainnya", "koleksi-lainnya": "koleksi-lainnya",
        "lainnya": "koleksi-lainnya", "lain": "koleksi-lainnya",
    }
    if raw not in aliases:
        raise ValueError("Kategori harus: Ruang Tamu, Ruang Makan, Kamar Tidur, atau Koleksi Lainnya.")
    return aliases[raw]


def display_category(category):
    return {
        "ruang-tamu": "Ruang Tamu",
        "ruang-makan": "Ruang Makan",
        "kamar-tidur": "Kamar Tidur",
        "koleksi-lainnya": "Koleksi Lainnya",
    }.get(category, category)


def parse_product_form(text):
    raw_fields = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip().lower(), value.strip()
        if value:
            raw_fields[key] = value

    aliases = {
        "nama produk": "name", "nama": "name", "kategori": "category", "stok": "stock",
        "deskripsi": "description", "tag 1": "tag1", "tag1": "tag1",
        "tag 2": "tag2", "tag2": "tag2", "tag 3": "tag3", "tag3": "tag3",
    }
    data = {aliases[k]: v for k, v in raw_fields.items() if k in aliases}
    required = ["name", "category", "stock", "description", "tag1", "tag2", "tag3"]
    if any(not data.get(k) for k in required):
        raise ValueError("Data belum lengkap. Isi Nama Produk, Kategori, Stok, Deskripsi, Tag 1, Tag 2, Tag 3.")

    data["category"] = normalize_category(data["category"])
    try:
        data["stock"] = int(data["stock"])
    except ValueError:
        raise ValueError("Stok harus berupa angka.")
    if data["stock"] < 0:
        raise ValueError("Stok tidak boleh negatif.")
    return data


def product_card_html(code, num, draft, image_paths):
    stock = int(draft["stock"])
    status_class = "available" if stock > 0 else "sold-out"
    status_label = status_text(stock)
    name = html_lib.escape(draft["name"])
    desc = html_lib.escape(draft["description"])
    tags = [html_lib.escape(draft[f"tag{i}"]) for i in (1, 2, 3)]
    main = html_lib.escape(image_paths[0])
    if len(image_paths) == 1:
        click = f"openImage('{main}')"
    else:
        imgs = ",".join(f"'{html_lib.escape(p)}'" for p in image_paths)
        click = f"openGallery([{imgs}], 0)"

    return f"""

            <!-- =================================
                 {num:02d} AUTO ADDED BY TELEGRAM BOT
            ================================== -->

            <div class="product-card" data-category="{draft['category']}" data-code="{code}">

                <div class="product-image" onclick="{click}">
                    <span class="product-status {status_class}">{status_label}</span>
                    <img src="{main}" alt="{name}">
                </div>

                <div class="product-info">
                    <div class="product-number">KOLEKSI {num:02d}</div>
                    <h2>{name}</h2>
                    <p>{desc}</p>

                    <div class="product-tags">
                        <span>{tags[0]}</span>
                        <span>{tags[1]}</span>
                        <span>{tags[2]}</span>
                    </div>

                    <div class="product-actions">
                        <button type="button" class="product-action-button price-button" onclick="sendProductToWhatsApp(this, 'harga')">HARGA</button>
                        <button type="button" class="product-action-button order-button" onclick="sendProductToWhatsApp(this, 'pesan')">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                                <circle cx="9" cy="20" r="1"></circle>
                                <circle cx="19" cy="20" r="1"></circle>
                                <path d="M3 4h2l2.4 10.2a2 2 0 0 0 2 1.5h7.9a2 2 0 0 0 2-1.6L21 7H6"></path>
                            </svg>
                            PESAN PRODUK
                        </button>
                    </div>
                </div>
            </div>
"""


def insert_product_card(current_html, card_html):
    marker = '<div class="filter-empty" id="filterEmpty">'
    idx = current_html.find(marker)
    if idx == -1:
        raise RuntimeError("Marker filter-empty tidak ditemukan. Bot berhenti agar produk.html tidak rusak.")
    return current_html[:idx] + card_html + "\n            " + current_html[idx:]


async def get_telegram_image_bytes(context, file_id):
    tg_file = await context.bot.get_file(file_id)
    buf = BytesIO()
    await tg_file.download_to_memory(out=buf)
    return buf.getvalue()



def find_product_card_span(current_html, code):
    """Return (start, end, block) for a product-card with data-code=CODE.
    Uses balanced <div> counting so it works for legacy and bot-added cards.
    """
    patterns = [
        f'data-code="{code}"',
        f"data-code='{code}'",
    ]
    code_pos = -1
    for p in patterns:
        code_pos = current_html.find(p)
        if code_pos != -1:
            break
    if code_pos == -1:
        raise KeyError(f"{code} tidak ditemukan di produk.html.")

    start = current_html.rfind('<div class="product-card"', 0, code_pos + 1)
    if start == -1:
        raise RuntimeError(f"Card {code} ditemukan tapi awal product-card tidak terbaca.")

    token_re = re.compile(r'<div\\b|</div\\s*>', re.I)
    depth = 0
    for m in token_re.finditer(current_html, start):
        token = m.group(0).lower()
        if token.startswith('<div'):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return start, m.end(), current_html[start:m.end()]
    raise RuntimeError(f"Card {code} tidak tertutup dengan benar.")


def extract_product_card_data(block, fallback_stock=0):
    category_m = re.search(r'data-category=["\\\']([^"\\\']+)["\\\']', block, re.I)
    name_m = re.search(r'<h2>\\s*(.*?)\\s*</h2>', block, re.I | re.S)
    p_m = re.search(r'<div class="product-info">.*?<p>\\s*(.*?)\\s*</p>', block, re.I | re.S)
    tags_m = re.search(r'<div class="product-tags">(.*?)</div>', block, re.I | re.S)
    tags = []
    if tags_m:
        tags = [re.sub(r'<[^>]+>', '', x).strip() for x in re.findall(r'<span>\\s*(.*?)\\s*</span>', tags_m.group(1), re.I | re.S)]
    while len(tags) < 3:
        tags.append('')

    def clean(s):
        return html_lib.unescape(re.sub(r'\\s+', ' ', s or '').strip())

    return {
        'name': clean(name_m.group(1) if name_m else ''),
        'category': category_m.group(1) if category_m else 'koleksi-lainnya',
        'stock': int(fallback_stock),
        'description': clean(p_m.group(1) if p_m else ''),
        'tag1': clean(tags[0]),
        'tag2': clean(tags[1]),
        'tag3': clean(tags[2]),
    }


def extract_image_paths(block):
    paths = re.findall(r"[\"']((?:images|images-Home)/[^\"']+?\\.(?:jpg|jpeg|png|webp))[\"']", block, re.I)
    unique = []
    for p in paths:
        if p not in unique:
            unique.append(p)
    return unique


def replace_product_card(current_html, code, new_block):
    start, end, _ = find_product_card_span(current_html, code)
    return current_html[:start] + new_block.strip('\n') + current_html[end:]


def remove_product_card(current_html, code):
    start, end, _ = find_product_card_span(current_html, code)
    # Remove adjacent bot comment when directly above, but never require it.
    comment_start = current_html.rfind('<!--', max(0, start - 400), start)
    comment_end = current_html.find('-->', comment_start, start) if comment_start != -1 else -1
    if comment_start != -1 and comment_end != -1 and comment_end < start:
        comment_text = current_html[comment_start:comment_end + 3]
        if 'AUTO ADDED BY TELEGRAM BOT' in comment_text:
            start = comment_start
    return current_html[:start] + current_html[end:]


def product_number_from_code(code):
    return int(code[2:])


def update_card_images(block, code, image_paths):
    if not image_paths:
        raise ValueError('Minimal satu foto diperlukan.')
    main = html_lib.escape(image_paths[0])
    if len(image_paths) == 1:
        onclick = f"openImage('{main}')"
    else:
        imgs = ','.join(f"'{html_lib.escape(p)}'" for p in image_paths)
        onclick = f"openGallery([{imgs}], 0)"

    block = re.sub(
        r'onclick="(?:openImage\\([^\"]*\\)|openGallery\\([^\"]*\\))"',
        f'onclick="{onclick}"',
        block,
        count=1,
        flags=re.I | re.S,
    )
    block = re.sub(
        r'(<div\\s+class="product-image"[^>]*>.*?<img\\b[^>]*?\\bsrc=")[^"]+("[^>]*>)',
        rf'\\1{main}\\2',
        block,
        count=1,
        flags=re.I | re.S,
    )
    return block


def edit_product_card_html(code, draft, image_paths):
    num = product_number_from_code(code)
    return product_card_html(code, num, draft, image_paths)


EDIT_TEMPLATE = """✏️ EDIT PRODUK {code}\n\nCopy template di bawah, ubah yang perlu, lalu kirim kembali dalam SATU pesan:\n\nNama Produk: {name}\nKategori: {category}\nStok: {stock}\nDeskripsi: {description}\nTag 1: {tag1}\nTag 2: {tag2}\nTag 3: {tag3}\n\nKategori: Ruang Tamu / Ruang Makan / Kamar Tidur / Koleksi Lainnya\n"""



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_admin(update): return
    await update.message.reply_text(
        "🪵 RAHMAT JEPARA — ADMIN BOT\n\n"
        "STOK:\n• jt001 laku\n• jt001 stok 2\n• jt001 available\n• jt001 soldout\n\n"
        "PRODUK:\n• /produkbaru\n• /editproduk JT017\n• /gantifoto JT017\n• /hapusproduk JT017\n\n"
        "GARANSI:\n• /garansi\n• /cekgaransi KODE\n• /batalkangaransi KODE\n\n"
        "DAFTAR:\n/stok\n/available\n/soldout\n/ringkasan\n/help"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_admin(update): return
    await update.message.reply_text(
        "📖 COMMAND ADMIN\n\n"
        "jt001 laku → kurangi stok 1\n"
        "jt001 stok 3 → set stok ke 3\n"
        "jt001 available → jika 0, jadi 1\n"
        "jt001 soldout → stok jadi 0\n\n"
        "/stok → semua produk\n/available → yang tersedia\n/soldout → yang habis\n\n"
        "/produkbaru → tambah produk baru\n"
        "/editproduk JT017 → edit data produk\n"
        "/gantifoto JT017 → ganti semua foto produk\n"
        "/hapusproduk JT017 → hapus produk dari website\n\n"
        "/garansi → daftar semua garansi\n"
        "/cekgaransi KODE → cek satu kode garansi\n"
        "/batalkangaransi KODE → nonaktifkan kode yang salah\n\n"
        "/ringkasan → total stok/status\n"
        "/selesai → selesai kirim foto\n/batal → batalkan draft/aktivasi garansi"
    )


async def send_inventory_list(update: Update, mode="all"):
    if await reject_if_not_admin(update): return
    try:
        data, _ = github_get_inventory()
    except Exception as exc:
        await update.message.reply_text(f"❌ Gagal membaca stok dari GitHub:\n{exc}")
        return
    rows = []
    for code, product in sorted(data.get("products", {}).items()):
        stock = int(product.get("stock", 0))
        if mode == "available" and stock <= 0: continue
        if mode == "soldout" and stock > 0: continue
        rows.append(format_product(code, product))
    title = {"all":"📦 SEMUA STOK", "available":"🟢 AVAILABLE", "soldout":"🔴 SOLD OUT"}[mode]
    await update.message.reply_text(title + "\n\n" + ("\n".join(rows) if rows else "Tidak ada produk."))


async def stok(update: Update, context: ContextTypes.DEFAULT_TYPE): await send_inventory_list(update, "all")
async def available(update: Update, context: ContextTypes.DEFAULT_TYPE): await send_inventory_list(update, "available")
async def soldout(update: Update, context: ContextTypes.DEFAULT_TYPE): await send_inventory_list(update, "soldout")



async def ringkasan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_admin(update): return
    try:
        data, _ = github_get_inventory()
        products = data.get('products', {})
        total = len(products)
        available_count = sum(1 for p in products.values() if int(p.get('stock', 0)) > 0)
        soldout_count = total - available_count
        total_units = sum(max(0, int(p.get('stock', 0))) for p in products.values())
        await update.message.reply_text(
            '📊 RINGKASAN INVENTORY RAHMAT JEPARA\n\n'
            f'Total koleksi: {total}\n'
            f'🟢 Available: {available_count}\n'
            f'🔴 Sold out: {soldout_count}\n'
            f'📦 Total unit stok: {total_units}\n\n'
            'Gunakan /stok untuk detail semua produk.'
        )
    except Exception as exc:
        await update.message.reply_text(f'❌ Gagal membaca ringkasan:\n{exc}')


async def editproduk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_admin(update): return
    if not context.args:
        await update.message.reply_text('Contoh: /editproduk JT017')
        return
    try:
        code = normalize_code(context.args[0])
        inv, _ = github_get_inventory()
        product = get_product(inv, code)
        current_html, _ = gh_get_text(PRODUCT_HTML_PATH)
        _, _, block = find_product_card_span(current_html, code)
        data = extract_product_card_data(block, int(product.get('stock', 0)))
        EDIT_PRODUCT_DRAFTS[ADMIN_ID] = {
            'stage': 'waiting_form',
            'code': code,
            'old_data': data,
            'images': extract_image_paths(block),
        }
        await update.message.reply_text(EDIT_TEMPLATE.format(
            code=code,
            name=data['name'],
            category=display_category(data['category']),
            stock=data['stock'],
            description=data['description'],
            tag1=data['tag1'], tag2=data['tag2'], tag3=data['tag3'],
        ))
    except Exception as exc:
        await update.message.reply_text(f'❌ Gagal membuka produk untuk diedit:\n{exc}')


async def handle_edit_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    draft = EDIT_PRODUCT_DRAFTS.get(ADMIN_ID)
    if not draft or draft.get('stage') != 'waiting_form':
        return False
    try:
        data = parse_product_form(update.message.text or '')
    except ValueError as exc:
        await update.message.reply_text(f'❌ {exc}\n\nKirim ulang template yang lengkap.')
        return True

    draft['data'] = data
    draft['stage'] = 'waiting_confirm'
    code = draft['code']
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton('✅ SIMPAN EDIT', callback_data=f'edit_publish:{code}'),
        InlineKeyboardButton('❌ BATAL', callback_data=f'edit_cancel:{code}'),
    ]])
    await update.message.reply_text(
        '✏️ PREVIEW EDIT PRODUK\n\n'
        f"{code} — KOLEKSI {product_number_from_code(code):02d}\n"
        f"Nama: {data['name']}\nKategori: {display_category(data['category'])}\n"
        f"Stok: {data['stock']}\nStatus: {status_icon(data['stock'])} {status_text(data['stock'])}\n"
        f"Tag: {data['tag1']} • {data['tag2']} • {data['tag3']}\n\n"
        'Foto tetap seperti sekarang. Tekan SIMPAN EDIT jika sudah benar.',
        reply_markup=kb,
    )
    return True


async def handle_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text('⛔ Bot ini khusus admin Rahmat Jepara.')
        return
    action, code = query.data.split(':', 1)
    draft = EDIT_PRODUCT_DRAFTS.get(ADMIN_ID)
    if not draft or draft.get('code') != code:
        await query.edit_message_text('Draft edit sudah tidak aktif.')
        return
    if action == 'edit_cancel':
        EDIT_PRODUCT_DRAFTS.pop(ADMIN_ID, None)
        await query.edit_message_text('❌ Edit produk dibatalkan.')
        return

    await query.edit_message_text('⏳ Menyimpan perubahan produk ke GitHub...')
    try:
        inv, _ = github_get_inventory()
        current_html, _ = gh_get_text(PRODUCT_HTML_PATH)
        get_product(inv, code)
        images = draft.get('images') or []
        if not images:
            _, _, current_block = find_product_card_span(current_html, code)
            images = extract_image_paths(current_block)
        data = draft['data']
        new_block = edit_product_card_html(code, data, images)
        new_html = replace_product_card(current_html, code, new_block)

        inv['products'][code]['stock'] = int(data['stock'])
        inv['products'][code]['status'] = status_text(int(data['stock']))
        inv['products'][code]['koleksi'] = f"KOLEKSI {product_number_from_code(code):02d}"
        inv['updated_at'] = datetime.now(timezone.utc).isoformat()

        changed = {
            PRODUCT_HTML_PATH: new_html.encode('utf-8'),
            STATUS_PATH: json.dumps(inv, ensure_ascii=False, indent=2).encode('utf-8'),
        }
        sha = gh_atomic_commit(changed, f'Edit {code}: {data["name"]}')
        EDIT_PRODUCT_DRAFTS.pop(ADMIN_ID, None)
        await query.edit_message_text(
            '✅ PRODUK BERHASIL DIEDIT\n\n'
            f'{code} — {data["name"]}\nStok: {data["stock"]}\n'
            f'Git commit: {sha[:8]}\nGitHub Pages akan update setelah deploy.'
        )
    except Exception as exc:
        await query.edit_message_text(f'❌ Edit gagal:\n{exc}\n\nDraft masih tersimpan.')


async def hapusproduk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_admin(update): return
    if not context.args:
        await update.message.reply_text('Contoh: /hapusproduk JT017')
        return
    try:
        code = normalize_code(context.args[0])
        inv, _ = github_get_inventory()
        product = get_product(inv, code)
        current_html, _ = gh_get_text(PRODUCT_HTML_PATH)
        _, _, block = find_product_card_span(current_html, code)
        data = extract_product_card_data(block, int(product.get('stock', 0)))
        DELETE_PRODUCT_DRAFTS[ADMIN_ID] = {'code': code, 'name': data['name']}
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton('🗑️ YA, HAPUS', callback_data=f'delete_publish:{code}'),
            InlineKeyboardButton('❌ BATAL', callback_data=f'delete_cancel:{code}'),
        ]])
        await update.message.reply_text(
            '⚠️ KONFIRMASI HAPUS PRODUK\n\n'
            f'{code} — {data["name"]}\n{product.get("koleksi", "")}\n\n'
            'Produk akan dihapus dari halaman Produk dan inventory.\n'
            'File gambar sengaja TIDAK dihapus dari repo agar aman.',
            reply_markup=kb,
        )
    except Exception as exc:
        await update.message.reply_text(f'❌ Gagal membuka produk:\n{exc}')


async def handle_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text('⛔ Bot ini khusus admin Rahmat Jepara.')
        return
    action, code = query.data.split(':', 1)
    draft = DELETE_PRODUCT_DRAFTS.get(ADMIN_ID)
    if not draft or draft.get('code') != code:
        await query.edit_message_text('Konfirmasi hapus sudah tidak aktif.')
        return
    if action == 'delete_cancel':
        DELETE_PRODUCT_DRAFTS.pop(ADMIN_ID, None)
        await query.edit_message_text('❌ Hapus produk dibatalkan.')
        return

    await query.edit_message_text('⏳ Menghapus produk dari website...')
    try:
        inv, _ = github_get_inventory()
        current_html, _ = gh_get_text(PRODUCT_HTML_PATH)
        get_product(inv, code)
        new_html = remove_product_card(current_html, code)
        removed = inv.setdefault('products', {}).pop(code)
        inv['updated_at'] = datetime.now(timezone.utc).isoformat()
        changed = {
            PRODUCT_HTML_PATH: new_html.encode('utf-8'),
            STATUS_PATH: json.dumps(inv, ensure_ascii=False, indent=2).encode('utf-8'),
        }
        sha = gh_atomic_commit(changed, f'Hapus produk {code}')
        DELETE_PRODUCT_DRAFTS.pop(ADMIN_ID, None)
        await query.edit_message_text(
            '✅ PRODUK BERHASIL DIHAPUS\n\n'
            f'{code} — {removed.get("koleksi", code)}\n'
            f'Git commit: {sha[:8]}\n\n'
            'Gambar lama tetap disimpan di repo sebagai cadangan.'
        )
    except Exception as exc:
        await query.edit_message_text(f'❌ Hapus gagal:\n{exc}')


async def gantifoto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_admin(update): return
    if not context.args:
        await update.message.reply_text('Contoh: /gantifoto JT017')
        return
    try:
        code = normalize_code(context.args[0])
        inv, _ = github_get_inventory()
        get_product(inv, code)
        current_html, _ = gh_get_text(PRODUCT_HTML_PATH)
        _, _, block = find_product_card_span(current_html, code)
        PHOTO_REPLACE_DRAFTS[ADMIN_ID] = {
            'code': code,
            'stage': 'waiting_photos',
            'photos': [],
            'old_images': extract_image_paths(block),
        }
        await update.message.reply_text(
            f'📸 GANTI FOTO {code}\n\n'
            'Kirim semua foto baru sekarang.\n'
            'Foto PERTAMA = foto utama.\nFoto berikutnya = slide.\n\n'
            'Kalau selesai, ketik /selesai.\nGunakan /batal untuk membatalkan.'
        )
    except Exception as exc:
        await update.message.reply_text(f'❌ Produk tidak bisa dibuka:\n{exc}')


async def handle_replace_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_admin(update): return False
    draft = PHOTO_REPLACE_DRAFTS.get(ADMIN_ID)
    if not draft or draft.get('stage') != 'waiting_photos':
        return False
    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document and (update.message.document.mime_type or '').startswith('image/'):
        file_id = update.message.document.file_id
    if not file_id:
        return False
    if len(draft['photos']) >= 10:
        await update.message.reply_text('⚠️ Maksimal 10 foto. Ketik /selesai.')
        return True
    draft['photos'].append(await get_telegram_image_bytes(context, file_id))
    n = len(draft['photos'])
    await update.message.reply_text(
        f'✅ {"FOTO UTAMA" if n == 1 else f"SLIDE {n-1}"} diterima. Total: {n}\n'
        'Kirim foto berikutnya atau /selesai.'
    )
    return True


async def finish_replace_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    draft = PHOTO_REPLACE_DRAFTS.get(ADMIN_ID)
    if not draft:
        return False
    if not draft.get('photos'):
        await update.message.reply_text('❌ Belum ada foto baru.')
        return True
    draft['stage'] = 'waiting_confirm'
    code = draft['code']
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton('✅ GANTI FOTO', callback_data=f'photo_publish:{code}'),
        InlineKeyboardButton('❌ BATAL', callback_data=f'photo_cancel:{code}'),
    ]])
    await update.message.reply_text(
        f'📸 PREVIEW GANTI FOTO\n\nProduk: {code}\nFoto baru: {len(draft["photos"])}\n\n'
        'Foto pertama akan menjadi foto utama.',
        reply_markup=kb,
    )
    return True


async def handle_photo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text('⛔ Bot ini khusus admin Rahmat Jepara.')
        return
    action, code = query.data.split(':', 1)
    draft = PHOTO_REPLACE_DRAFTS.get(ADMIN_ID)
    if not draft or draft.get('code') != code:
        await query.edit_message_text('Draft ganti foto sudah tidak aktif.')
        return
    if action == 'photo_cancel':
        PHOTO_REPLACE_DRAFTS.pop(ADMIN_ID, None)
        await query.edit_message_text('❌ Ganti foto dibatalkan.')
        return

    await query.edit_message_text('⏳ Mengupload foto baru ke GitHub...')
    try:
        current_html, _ = gh_get_text(PRODUCT_HTML_PATH)
        start, end, block = find_product_card_span(current_html, code)
        num = product_number_from_code(code)
        image_paths, changed = [], {}
        for i, image_bytes in enumerate(draft['photos'], start=1):
            path = f'{IMAGE_FOLDER}/koleksi-{num:02d}-{i}.jpg'
            image_paths.append(path)
            changed[path] = image_bytes
        new_block = update_card_images(block, code, image_paths)
        new_html = current_html[:start] + new_block + current_html[end:]
        changed[PRODUCT_HTML_PATH] = new_html.encode('utf-8')
        sha = gh_atomic_commit(changed, f'Ganti foto {code}')
        PHOTO_REPLACE_DRAFTS.pop(ADMIN_ID, None)
        await query.edit_message_text(
            '✅ FOTO PRODUK BERHASIL DIGANTI\n\n'
            f'{code}\nFoto baru: {len(image_paths)}\nGit commit: {sha[:8]}\n'
            'GitHub Pages akan update setelah deploy.'
        )
    except Exception as exc:
        await query.edit_message_text(f'❌ Ganti foto gagal:\n{exc}\n\nDraft masih tersimpan.')



PRODUCT_TEMPLATE = """🪵 TAMBAH PRODUK BARU

Copy template di bawah, isi semuanya, lalu kirim kembali dalam SATU pesan:

Nama Produk:
Kategori:
Stok:
Deskripsi:
Tag 1:
Tag 2:
Tag 3:

Kategori yang boleh dipakai:
• Ruang Tamu
• Ruang Makan
• Kamar Tidur
• Koleksi Lainnya

Setelah data diterima, kirim foto produk.
Foto PERTAMA = foto utama.
Foto berikutnya = slide.
Kalau semua foto selesai, ketik /selesai.
"""


async def garansi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_admin(update): return
    try:
        data, _ = github_get_warranties()
        items = data.get("warranties", {})
        if not items:
            await update.message.reply_text("🔐 Belum ada kode garansi yang diaktifkan.")
            return
        rows = [format_warranty(code, record) for code, record in sorted(items.items())]
        active = sum(1 for r in items.values() if warranty_status(r) == "ACTIVE")
        expired = sum(1 for r in items.values() if warranty_status(r) == "EXPIRED")
        cancelled = sum(1 for r in items.values() if warranty_status(r) == "CANCELLED")
        await update.message.reply_text(
            "🔐 DAFTAR GARANSI RAHMAT JEPARA\n\n"
            + "\n".join(rows)
            + f"\n\nAktif: {active} | Expired: {expired} | Dibatalkan: {cancelled}"
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ Gagal membaca garansi:\n{exc}")


async def cekgaransi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_admin(update): return
    if not context.args:
        await update.message.reply_text("Contoh: /cekgaransi RJ-JT001-8K29X")
        return
    try:
        code = normalize_warranty_code(context.args[0])
        data, _ = github_get_warranties()
        record = data.get("warranties", {}).get(code)
        if not record:
            await update.message.reply_text(f"❌ Kode garansi {code} tidak ditemukan.")
            return
        status = warranty_status(record)
        icon = {"ACTIVE": "✅", "EXPIRED": "⚠️", "CANCELLED": "⛔", "INVALID": "❌"}.get(status, "❓")
        await update.message.reply_text(
            f"{icon} GARANSI {status}\n\n"
            f"Kode: {code}\n"
            f"Produk: {record.get('product_code', '-')}\n"
            f"Mulai: {record.get('activated_at', '-')}\n"
            f"Berakhir: {record.get('expires_at', '-')}"
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ Gagal mengecek garansi:\n{exc}")


async def batalkangaransi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_admin(update): return
    if not context.args:
        await update.message.reply_text("Contoh: /batalkangaransi RJ-JT001-8K29X")
        return
    try:
        code = normalize_warranty_code(context.args[0])
        data, sha = github_get_warranties()
        record = data.get("warranties", {}).get(code)
        if not record:
            await update.message.reply_text(f"❌ Kode garansi {code} tidak ditemukan.")
            return
        record["cancelled"] = True
        record["cancelled_at"] = datetime.now(JAKARTA_TZ).isoformat(timespec="seconds")
        github_save_warranties(data, sha, f"Batalkan garansi {code}")
        await update.message.reply_text(f"⛔ Garansi {code} berhasil dibatalkan.")
    except Exception as exc:
        await update.message.reply_text(f"❌ Gagal membatalkan garansi:\n{exc}")


async def produkbaru(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_admin(update): return
    NEW_PRODUCT_DRAFTS[ADMIN_ID] = {"stage": "waiting_form", "data": None, "photos": []}
    await update.message.reply_text(PRODUCT_TEMPLATE)


async def batal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_admin(update): return
    cancelled = False
    for store in (NEW_PRODUCT_DRAFTS, EDIT_PRODUCT_DRAFTS, PHOTO_REPLACE_DRAFTS, DELETE_PRODUCT_DRAFTS, WARRANTY_DRAFTS):
        if store.pop(ADMIN_ID, None):
            cancelled = True
    await update.message.reply_text("❌ Draft dibatalkan." if cancelled else "Tidak ada draft yang aktif.")


async def handle_product_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    draft = NEW_PRODUCT_DRAFTS.get(ADMIN_ID)
    if not draft or draft.get("stage") != "waiting_form":
        return False
    try:
        data = parse_product_form(update.message.text or "")
    except ValueError as exc:
        await update.message.reply_text(f"❌ {exc}\n\nKirim ulang template yang sudah lengkap.")
        return True

    try:
        inv, _ = github_get_inventory()
        num = next_product_number(inv)
        code_preview = f"JT{num:03d}"
        coll_preview = f"KOLEKSI {num:02d}"
    except Exception:
        code_preview = coll_preview = "otomatis saat publish"

    draft["data"] = data
    draft["stage"] = "waiting_photos"
    await update.message.reply_text(
        "✅ DATA PRODUK DITERIMA\n\n"
        f"Calon kode: {code_preview}\nCalon koleksi: {coll_preview}\n"
        f"Nama: {data['name']}\nKategori: {display_category(data['category'])}\nStok: {data['stock']}\n\n"
        "📸 Sekarang kirim foto produk.\nFoto pertama = FOTO UTAMA.\nFoto selanjutnya = SLIDE.\n\nKalau selesai, ketik /selesai."
    )
    return True


async def handle_product_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_admin(update): return
    if await handle_replace_photo(update, context):
        return
    draft = NEW_PRODUCT_DRAFTS.get(ADMIN_ID)
    if not draft or draft.get("stage") != "waiting_photos": return

    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document and (update.message.document.mime_type or "").startswith("image/"):
        file_id = update.message.document.file_id
    if not file_id: return

    if len(draft["photos"]) >= 10:
        await update.message.reply_text("⚠️ Maksimal 10 foto. Ketik /selesai untuk lanjut.")
        return

    draft["photos"].append(await get_telegram_image_bytes(context, file_id))
    n = len(draft["photos"])
    label = "FOTO UTAMA" if n == 1 else f"SLIDE {n-1}"
    await update.message.reply_text(f"✅ {label} diterima. Total foto: {n}\nKirim foto berikutnya atau ketik /selesai.")


async def selesai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_admin(update): return
    if await finish_replace_photos(update, context):
        return
    draft = NEW_PRODUCT_DRAFTS.get(ADMIN_ID)
    if not draft:
        await update.message.reply_text("Tidak ada draft produk baru yang aktif.")
        return
    if draft.get("stage") != "waiting_photos":
        await update.message.reply_text("Isi data produk dulu dari /produkbaru.")
        return
    if not draft.get("photos"):
        await update.message.reply_text("❌ Belum ada foto. Kirim minimal 1 foto utama.")
        return

    try:
        inv, _ = github_get_inventory()
        num = next_product_number(inv)
    except Exception as exc:
        await update.message.reply_text(f"❌ Gagal membaca nomor koleksi terakhir:\n{exc}")
        return

    draft["stage"] = "waiting_confirm"
    data = draft["data"]
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ PUBLISH", callback_data="new_product_publish"),
        InlineKeyboardButton("❌ BATAL", callback_data="new_product_cancel"),
    ]])
    await update.message.reply_text(
        "🪵 PREVIEW PRODUK BARU\n\n"
        f"Kode: JT{num:03d}\nKoleksi: KOLEKSI {num:02d}\nNama: {data['name']}\n"
        f"Kategori: {display_category(data['category'])}\nStok: {data['stock']}\n"
        f"Status: {status_icon(data['stock'])} {status_text(data['stock'])}\n"
        f"Foto: {len(draft['photos'])}\nTag: {data['tag1']} • {data['tag2']} • {data['tag3']}\n\n"
        "Kalau sudah benar, tekan PUBLISH.", reply_markup=kb
    )


async def handle_new_product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ Bot ini khusus admin Rahmat Jepara.")
        return

    draft = NEW_PRODUCT_DRAFTS.get(ADMIN_ID)
    if not draft or draft.get("stage") != "waiting_confirm":
        await query.edit_message_text("Draft ini sudah tidak aktif. Jalankan /produkbaru lagi.")
        return

    if query.data == "new_product_cancel":
        NEW_PRODUCT_DRAFTS.pop(ADMIN_ID, None)
        await query.edit_message_text("❌ Produk baru dibatalkan.")
        return
    if query.data != "new_product_publish": return

    await query.edit_message_text("⏳ Sedang publish produk ke GitHub...")
    try:
        inventory, _ = github_get_inventory()
        current_html, _ = gh_get_text(PRODUCT_HTML_PATH)
        num = next_product_number(inventory)
        code = f"JT{num:03d}"
        collection = f"KOLEKSI {num:02d}"
        data = draft["data"]

        image_paths, changed = [], {}
        for i, image_bytes in enumerate(draft["photos"], start=1):
            path = f"{IMAGE_FOLDER}/koleksi-{num:02d}-{i}.jpg"
            image_paths.append(path)
            changed[path] = image_bytes

        new_html = insert_product_card(current_html, product_card_html(code, num, data, image_paths))
        inventory.setdefault("products", {})[code] = {
            "koleksi": collection,
            "stock": int(data["stock"]),
            "status": status_text(int(data["stock"])),
        }
        inventory["updated_at"] = datetime.now(timezone.utc).isoformat()
        changed[PRODUCT_HTML_PATH] = new_html.encode("utf-8")
        changed[STATUS_PATH] = json.dumps(inventory, ensure_ascii=False, indent=2).encode("utf-8")

        commit_sha = gh_atomic_commit(changed, f"Tambah {code} {collection}: {data['name']}")
        NEW_PRODUCT_DRAFTS.pop(ADMIN_ID, None)
        await query.edit_message_text(
            "✅ PRODUK BERHASIL DIPUBLISH\n\n"
            f"{code} — {collection}\n{data['name']}\nFoto: {len(image_paths)}\n"
            f"Stok: {data['stock']}\nStatus: {status_icon(data['stock'])} {status_text(data['stock'])}\n\n"
            f"Git commit: {commit_sha[:8]}\nGitHub Pages akan update setelah deploy selesai."
        )
    except Exception as exc:
        draft["stage"] = "waiting_photos"
        await query.edit_message_text(f"❌ Publish gagal:\n{exc}\n\nDraft belum dihapus. Ketik /selesai untuk mencoba lagi.")


async def handle_inventory_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_admin(update): return
    if await handle_edit_form(update, context): return
    if await handle_product_form(update, context): return

    text = (update.message.text or "").strip()

    warranty_draft = WARRANTY_DRAFTS.get(ADMIN_ID)
    if warranty_draft and warranty_draft.get("stage") == "waiting_code":
        try:
            warranty_code = normalize_warranty_code(text)
            warranty_data, warranty_sha = github_get_warranties()
            warranties = warranty_data.setdefault("warranties", {})

            if warranty_code in warranties:
                await update.message.reply_text(
                    f"❌ Kode {warranty_code} sudah pernah dipakai.\n\n"
                    "Masukkan kode lain, atau ketik /batal untuk membatalkan."
                )
                return

            product_code = warranty_draft["product_code"]
            start_date, expires_date = warranty_dates()
            warranties[warranty_code] = {
                "product_code": product_code,
                "activated_at": start_date.isoformat(),
                "expires_at": expires_date.isoformat(),
                "cancelled": False,
            }
            github_save_warranties(
                warranty_data, warranty_sha,
                f"Aktifkan garansi {warranty_code} untuk {product_code}"
            )
            WARRANTY_DRAFTS.pop(ADMIN_ID, None)
            await update.message.reply_text(
                "✅ GARANSI BERHASIL DIAKTIFKAN\n\n"
                f"Produk : {product_code}\n"
                f"Kode   : {warranty_code}\n"
                f"Mulai  : {start_date.strftime('%d-%m-%Y')}\n"
                f"Expired: {expires_date.strftime('%d-%m-%Y')}\n"
                "Status : ✅ ACTIVE\n\n"
                "Berikan kode ini kepada customer untuk klaim garansi di website."
            )
        except ValueError as exc:
            await update.message.reply_text(
                f"❌ {exc}\n\nMasukkan kode lain, atau ketik /batal untuk membatalkan."
            )
        except Exception as exc:
            await update.message.reply_text(
                f"❌ Gagal mengaktifkan garansi:\n{exc}\n\n"
                "Draft garansi masih aktif. Coba kirim kode lagi atau /batal."
            )
        return

    parts = text.split()
    if len(parts) < 2: return
    try:
        code = normalize_code(parts[0])
    except ValueError:
        return

    action = parts[1].lower()
    try:
        data, sha = github_get_inventory()
        product = get_product(data, code)
        old = int(product.get("stock", 0))
        if action == "laku":
            if old <= 0:
                await update.message.reply_text(
                    f"❌ {code} stoknya sudah 0 / SOLD OUT. Tidak ada stok yang bisa dikurangi."
                )
                return
            new = old - 1
        elif action == "available":
            new = old if old > 0 else 1
        elif action in {"soldout", "sold", "habis"}:
            new = 0
        elif action == "stok":
            if len(parts) < 3:
                await update.message.reply_text(f"Contoh: {code.lower()} stok 2")
                return
            try:
                new = int(parts[2])
            except ValueError:
                await update.message.reply_text("❌ Jumlah stok harus angka.")
                return
            if new < 0:
                await update.message.reply_text("❌ Stok tidak boleh negatif.")
                return
        else:
            await update.message.reply_text(
                "❓ Command tidak dikenali. Contoh: jt001 laku / jt001 stok 2 / "
                "jt001 available / jt001 soldout"
            )
            return

        product["stock"] = new
        product["status"] = status_text(new)
        github_save_inventory(data, sha, f"Inventory {code}: {old} -> {new}")
        await update.message.reply_text(
            f"✅ {code} — {product.get('koleksi', code)}\n\n"
            f"Stok sebelumnya: {old}\nStok sekarang: {new}\n"
            f"Status: {status_icon(new)} {status_text(new)}\n\n"
            "GitHub berhasil diperbarui."
        )

        if action == "laku":
            WARRANTY_DRAFTS[ADMIN_ID] = {
                "stage": "waiting_code",
                "product_code": code,
            }
            await update.message.reply_text(
                "🔐 AKTIVASI GARANSI 12 BULAN\n\n"
                f"Produk {code} baru saja ditandai laku.\n"
                "Masukkan KODE GARANSI unik yang mau diaktifkan.\n\n"
                "Contoh: RJ-JT001-8K29X\n\n"
                "Kode ini nanti diberikan ke customer.\n"
                "Ketik /batal jika transaksi ini tidak perlu dibuatkan garansi."
            )
    except Exception as exc:
        await update.message.reply_text(f"❌ Gagal memperbarui stok:\n{exc}")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stok", stok))
    app.add_handler(CommandHandler("available", available))
    app.add_handler(CommandHandler("soldout", soldout))
    app.add_handler(CommandHandler("produkbaru", produkbaru))
    app.add_handler(CommandHandler("editproduk", editproduk))
    app.add_handler(CommandHandler("gantifoto", gantifoto))
    app.add_handler(CommandHandler("hapusproduk", hapusproduk))
    app.add_handler(CommandHandler("ringkasan", ringkasan))
    app.add_handler(CommandHandler("garansi", garansi))
    app.add_handler(CommandHandler("cekgaransi", cekgaransi))
    app.add_handler(CommandHandler("batalkangaransi", batalkangaransi))
    app.add_handler(CommandHandler("selesai", selesai))
    app.add_handler(CommandHandler("batal", batal))
    app.add_handler(CallbackQueryHandler(handle_new_product_callback, pattern=r"^new_product_(publish|cancel)$"))
    app.add_handler(CallbackQueryHandler(handle_edit_callback, pattern=r"^edit_(publish|cancel):JT\d{3}$"))
    app.add_handler(CallbackQueryHandler(handle_delete_callback, pattern=r"^delete_(publish|cancel):JT\d{3}$"))
    app.add_handler(CallbackQueryHandler(handle_photo_callback, pattern=r"^photo_(publish|cancel):JT\d{3}$"))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_product_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_inventory_message))
    print("Rahmat Jepara Inventory + Warranty Bot v4 aktif...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
