import os
import re
import json
import base64
from datetime import datetime, timezone

import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_ID = int(os.environ["TELEGRAM_ADMIN_ID"])
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_OWNER = os.getenv("GITHUB_OWNER", "rahmatjepara")
GITHUB_REPO = os.getenv("GITHUB_REPO", "rahmat-jepara")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
STATUS_PATH = os.getenv("STATUS_PATH", "products-status.json")

GITHUB_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{STATUS_PATH}"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "X-GitHub-Api-Version": "2022-11-28",
}
CODE_RE = re.compile(r"^jt(\d{1,3})$", re.I)


def is_admin(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id == ADMIN_ID)


async def reject_if_not_admin(update: Update) -> bool:
    if is_admin(update):
        return False
    if update.effective_message:
        await update.effective_message.reply_text("⛔ Bot ini khusus admin Rahmat Jepara.")
    return True


def normalize_code(raw: str) -> str:
    m = CODE_RE.match(raw.strip())
    if not m:
        raise ValueError("Kode produk tidak valid.")
    return f"JT{int(m.group(1)):03d}"


def github_get_inventory():
    r = requests.get(GITHUB_API, headers=HEADERS, params={"ref": GITHUB_BRANCH}, timeout=30)
    r.raise_for_status()
    payload = r.json()
    data = json.loads(base64.b64decode(payload["content"]).decode("utf-8"))
    return data, payload["sha"]


def github_save_inventory(data, sha, message):
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    encoded = base64.b64encode(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")).decode("ascii")
    r = requests.put(
        GITHUB_API,
        headers=HEADERS,
        json={"message": message, "content": encoded, "sha": sha, "branch": GITHUB_BRANCH},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_admin(update): return
    await update.message.reply_text(
        "🪵 RAHMAT JEPARA — INVENTORY BOT\n\n"
        "Contoh:\n"
        "• jt001 laku\n"
        "• jt001 stok 2\n"
        "• jt001 available\n"
        "• jt001 soldout\n\n"
        "Daftar:\n/stok\n/available\n/soldout\n/help"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_admin(update): return
    await update.message.reply_text(
        "📖 COMMAND INVENTORY\n\n"
        "jt001 laku → kurangi stok 1\n"
        "jt001 stok 3 → set stok ke 3\n"
        "jt001 available → jika 0, jadi 1\n"
        "jt001 soldout → stok jadi 0\n\n"
        "/stok → semua produk\n"
        "/available → yang tersedia\n"
        "/soldout → yang habis"
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
    title = {"all":"📦 SEMUA STOK","available":"🟢 AVAILABLE","soldout":"🔴 SOLD OUT"}[mode]
    await update.message.reply_text(title + "\n\n" + ("\n".join(rows) if rows else "Tidak ada produk."))


async def stok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_inventory_list(update, "all")


async def available(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_inventory_list(update, "available")


async def soldout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_inventory_list(update, "soldout")


async def handle_inventory_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_admin(update): return
    text = (update.message.text or "").strip()
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
        old_stock = int(product.get("stock", 0))

        if action == "laku":
            new_stock = max(0, old_stock - 1)
        elif action == "available":
            new_stock = old_stock if old_stock > 0 else 1
        elif action in {"soldout", "sold", "habis"}:
            new_stock = 0
        elif action == "stok":
            if len(parts) < 3:
                await update.message.reply_text(f"Contoh: {code.lower()} stok 2")
                return
            try:
                new_stock = int(parts[2])
            except ValueError:
                await update.message.reply_text("❌ Jumlah stok harus angka.")
                return
            if new_stock < 0:
                await update.message.reply_text("❌ Stok tidak boleh negatif.")
                return
        else:
            await update.message.reply_text("❓ Command tidak dikenali. Contoh: jt001 laku / jt001 stok 2 / jt001 available / jt001 soldout")
            return

        product["stock"] = new_stock
        product["status"] = status_text(new_stock)
        github_save_inventory(data, sha, f"Inventory {code}: {old_stock} -> {new_stock}")

        await update.message.reply_text(
            f"✅ {code} — {product.get('koleksi', code)}\n\n"
            f"Stok sebelumnya: {old_stock}\n"
            f"Stok sekarang: {new_stock}\n"
            f"Status: {status_icon(new_stock)} {status_text(new_stock)}\n\n"
            "GitHub berhasil diperbarui. GitHub Pages biasanya butuh sedikit waktu untuk deploy."
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_inventory_message))
    print("Rahmat Jepara Inventory Bot aktif...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
