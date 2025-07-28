import streamlit as st
import sqlite3
import os
import uuid
from datetime import datetime, timezone, timedelta
from streamlit_autorefresh import st_autorefresh
import hashlib

# --- CONFIGURATION ---
DB_NAME = "chat.db"
UPLOAD_FOLDER = "uploads"
NOTIFICATION_SOUND = "notification_ding.mp3"  # Update with your path or URL as needed

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Messages table with reply_to
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            recipient TEXT,
            timestamp TEXT NOT NULL,
            type TEXT NOT NULL,
            content TEXT,
            file_path TEXT,
            reply_to TEXT
        )
    """)
    # Online users
    c.execute("""
        CREATE TABLE IF NOT EXISTS users_online (
            username TEXT PRIMARY KEY,
            last_seen TEXT NOT NULL
        )
    """)
    # User PINs for login
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_pins (
            username TEXT PRIMARY KEY,
            pin_hash TEXT NOT NULL
        )
    """)
    # Likes table
    c.execute("""
        CREATE TABLE IF NOT EXISTS message_likes (
            message_id TEXT NOT NULL,
            username TEXT NOT NULL,
            PRIMARY KEY (message_id, username),
            FOREIGN KEY (message_id) REFERENCES messages(id),
            FOREIGN KEY (username) REFERENCES user_pins(username)
        )
    """)
    conn.commit()
    conn.close()

def hash_pin(pin):
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()

def register_user_pin(username, pin):
    pin_hash = hash_pin(pin)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        INSERT INTO user_pins (username, pin_hash) VALUES (?, ?)
        ON CONFLICT(username) DO UPDATE SET pin_hash=excluded.pin_hash
    """, (username, pin_hash))
    conn.commit()
    conn.close()

def get_user_pin_hash(username):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT pin_hash FROM user_pins WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def verify_pin(username, pin):
    stored_hash = get_user_pin_hash(username)
    if not stored_hash:
        return False
    return stored_hash == hash_pin(pin)

def save_message(username, msg_type, content=None, file_bytes=None, file_name=None, recipient=None, reply_to=None):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    file_path = None
    msg_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    if file_bytes and file_name:
        file_path = os.path.join(UPLOAD_FOLDER, f"{msg_id}_{file_name}")
        with open(file_path, "wb") as f:
            f.write(file_bytes)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        INSERT INTO messages (id, username, recipient, timestamp, type, content, file_path, reply_to)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (msg_id, username, recipient, timestamp, msg_type, content, file_path, reply_to))
    conn.commit()
    conn.close()

def update_message_content(message_id, new_content):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        UPDATE messages SET content=? WHERE id=?
    """, (new_content, message_id))
    conn.commit()
    conn.close()

def get_messages(current_user, chat_with=None, search_text=None, page=1, page_size=20):
    offset = (page - 1) * page_size
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    base_query = """
        SELECT id, username, timestamp, type, content, file_path, recipient, reply_to
        FROM messages
    """
    params = []
    where_clauses = []

    if chat_with:
        where_clauses.append(
            "((username = ? AND recipient = ?) OR (username = ? AND recipient = ?))"
        )
        params.extend([current_user, chat_with, chat_with, current_user])
    else:
        where_clauses.append("(recipient IS NULL OR recipient = '')")

    if search_text:
        where_clauses.append("LOWER(content) LIKE ?")
        params.append(f"%{search_text.lower()}%")

    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    query = f"{base_query} {where_sql} ORDER BY timestamp ASC LIMIT ? OFFSET ?"
    params.extend([page_size, offset])

    c.execute(query, tuple(params))
    messages = c.fetchall()

    count_query = f"SELECT COUNT(*) FROM messages {where_sql}"
    count_params = tuple(params[:-2])
    c.execute(count_query, count_params)
    total_count = c.fetchone()[0]

    conn.close()
    return messages, total_count

def get_message_by_id(msg_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        SELECT id, username, timestamp, type, content, file_path, recipient, reply_to
        FROM messages WHERE id = ?
    """, (msg_id,))
    msg = c.fetchone()
    conn.close()
    return msg

def update_user_last_seen(username):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    c.execute("""
        INSERT INTO users_online(username, last_seen) VALUES (?, ?)
        ON CONFLICT(username) DO UPDATE SET last_seen=excluded.last_seen
    """, (username, now_iso))
    conn.commit()
    conn.close()

def get_online_users(timeout_seconds=120):
    threshold_time = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
    threshold_iso = threshold_time.isoformat()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT username FROM users_online WHERE last_seen > ?", (threshold_iso,))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_likes_for_message(message_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT username FROM message_likes WHERE message_id = ?", (message_id,))
    rows = c.fetchall()
    conn.close()
    return set([row[0] for row in rows])

def user_liked_message(username, message_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT 1 FROM message_likes WHERE message_id = ? AND username = ?", (message_id, username))
    liked = c.fetchone() is not None
    conn.close()
    return liked

def add_like(username, message_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("INSERT OR IGNORE INTO message_likes (message_id, username) VALUES (?, ?)", (message_id, username))
        conn.commit()
    finally:
        conn.close()

def remove_like(username, message_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM message_likes WHERE message_id = ? AND username = ?", (message_id, username))
    conn.commit()
    conn.close()

# --- SESSION STATE INIT ---
if "username" not in st.session_state:
    st.session_state.username = None
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "page" not in st.session_state:
    st.session_state.page = 1
if "page_size" not in st.session_state:
    st.session_state.page_size = 20
if "search_text" not in st.session_state:
    st.session_state.search_text = ""
if "reply_to" not in st.session_state:
    st.session_state.reply_to = None
if "last_global_msg_count" not in st.session_state:
    st.session_state.last_global_msg_count = 0
if "last_private_msg_count" not in st.session_state:
    st.session_state.last_private_msg_count = {}
if "edit_message_id" not in st.session_state:
    st.session_state.edit_message_id = None
if "edit_message_content" not in st.session_state:
    st.session_state.edit_message_content = ""

# --- APP START ---

init_db()
st.set_page_config(page_title="Secure Persistent Chat - Edit Feature", layout="wide")
st.title("🔒 Secure Persistent Chat with Message Editing, Likes, and PIN Access")

st_autorefresh(interval=5000, limit=None, key="refresh")

# LOGIN WITH PIN
if not st.session_state.username:
    username_input = st.text_input("Enter your username:")
    if st.button("Next") and username_input.strip():
        st.session_state.username = username_input.strip()
        st.rerun()
    else:
        st.stop()

if st.session_state.username and not st.session_state.authenticated:
    stored_pin_hash = get_user_pin_hash(st.session_state.username)
    if stored_pin_hash is None:
        st.markdown("**New user detected. Please register by setting a PIN.**")
        pin1 = st.text_input("Set a new PIN", type="password")
        pin2 = st.text_input("Confirm PIN", type="password")
        if pin1 and pin2 and st.button("Register PIN"):
            if pin1 == pin2:
                register_user_pin(st.session_state.username, pin1)
                st.success("PIN registered successfully! Please log in with your PIN.")
                st.rerun()
            else:
                st.error("PINs do not match. Try again.")
        st.stop()
    else:
        pin_input = st.text_input(f"Enter PIN for {st.session_state.username}", type="password")
        if pin_input and st.button("Login"):
            if verify_pin(st.session_state.username, pin_input):
                st.session_state.authenticated = True
                st.success("Login successful!")
                st.rerun()
            else:
                st.error("Incorrect PIN. Try again.")
        st.stop()

# USER AUTHENTICATED FROM HERE

update_user_last_seen(st.session_state.username)

# Online users sidebar
online_users = get_online_users()
st.sidebar.markdown("### 👥 Online Users")
if online_users:
    for user in online_users:
        label = f"**{user}** (You)" if user == st.session_state.username else user
        st.sidebar.markdown(label)
else:
    st.sidebar.markdown("_No users online_")

private_chat_users = [u for u in online_users if u != st.session_state.username]

chat_target = st.sidebar.selectbox("Select Chat Target", ["Global Chat"] + private_chat_users)
active_chat_user = None if chat_target == "Global Chat" else chat_target

# Pagination and search controls
page_size = st.sidebar.selectbox(
    "Messages per page", [10, 20, 50, 100],
    index=[10, 20, 50, 100].index(st.session_state.page_size),
)
if page_size != st.session_state.page_size:
    st.session_state.page_size = page_size
    st.session_state.page = 1

search_text = st.sidebar.text_input(
    "Search messages (text only)", value=st.session_state.search_text,
    help="Search messages in current chat (case-insensitive)",
)
if search_text != st.session_state.search_text:
    st.session_state.search_text = search_text
    st.session_state.page = 1

prev_col, page_info_col, next_col = st.sidebar.columns([1, 2, 1])
with prev_col:
    if st.button("Previous"):
        st.session_state.page = max(1, st.session_state.page - 1)

messages, total_count = get_messages(
    st.session_state.username,
    active_chat_user,
    search_text=st.session_state.search_text.strip() or None,
    page=st.session_state.page,
    page_size=st.session_state.page_size,
)

total_pages = max(1, (total_count + st.session_state.page_size - 1) // st.session_state.page_size)

with page_info_col:
    st.markdown(f"Page {st.session_state.page} of {total_pages}")
    st.markdown(f"Total messages: {total_count}")

with next_col:
    if st.session_state.page < total_pages:
        if st.button("Next"):
            st.session_state.page = min(total_pages, st.session_state.page + 1)

if search_text and total_count == 0:
    st.warning(f"No messages found matching '{search_text}'.")

# Notifications
def count_global_messages(msg_list):
    return len([msg for msg in msg_list if msg[6] in (None, '')])

def count_private_messages(msg_list):
    return len(msg_list)

if active_chat_user is None:
    global_msg_count = count_global_messages(messages)
    if global_msg_count > st.session_state.last_global_msg_count:
        try:
            st.audio(NOTIFICATION_SOUND)
        except Exception as e:
            st.error(f"Notification sound error: {e}")
        st.toast("New message in Global Chat! 💬")
        st.session_state.last_global_msg_count = global_msg_count
else:
    curr_private_count = count_private_messages(messages)
    last_count = st.session_state.last_private_msg_count.get(active_chat_user, 0)
    if curr_private_count > last_count:
        try:
            st.audio(NOTIFICATION_SOUND)
        except Exception as e:
            st.error(f"Notification sound error: {e}")
        st.toast(f"New private message from {active_chat_user}! 🔒")
        st.session_state.last_private_msg_count[active_chat_user] = curr_private_count

# Find last message by user in current chat (needed for edit)
last_user_msg_id = None
for m in reversed(messages):
    msg_id, user, *_ = m
    if user == st.session_state.username:
        last_user_msg_id = msg_id
        break

# Display chat messages with reply, like, and edit
chat_title = "Global Chat" if active_chat_user is None else f"Private Chat with {active_chat_user}"
st.subheader(f"Chat History - {chat_title}")

if not messages:
    st.info("No messages to display on this page.")

for (
    msg_id, user, tstamp, msg_type, content, file_path, recipient, reply_to
) in messages:
    with st.chat_message("user" if user == st.session_state.username else "assistant"):
        # Username and timestamp
        try:
            local_dt = datetime.fromisoformat(tstamp)
            local_dt_str = local_dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            local_dt_str = tstamp
        st.markdown(f"<small><b>{user}</b> · {local_dt_str}</small>", unsafe_allow_html=True)

        # Reply preview
        reply_preview = None
        if reply_to:
            replied_msg = get_message_by_id(reply_to)
            if replied_msg:
                r_id, r_user, r_ts, r_type, r_content, r_file_path, r_recipient, r_reply_to = replied_msg
                if r_type == "text":
                    reply_preview = f"**{r_user} said:** {r_content}"
                else:
                    reply_preview = f"**{r_user} sent a {r_type} message**"
        if reply_preview:
            st.markdown(f"> {reply_preview}", unsafe_allow_html=True)

        # Message Editing Section
        is_editing_this_msg = (st.session_state.edit_message_id == msg_id)

        if is_editing_this_msg and msg_type == "text":
            edit_content = st.text_area(
                "Edit your message:",
                value=st.session_state.edit_message_content or content,
                key=f"edit-content-{msg_id}"
            )
            col_save, col_cancel = st.columns(2)
            with col_save:
                if st.button("Save", key=f"save-btn-{msg_id}"):
                    update_message_content(msg_id, edit_content.strip())
                    st.session_state.edit_message_id = None
                    st.session_state.edit_message_content = ""
                    st.rerun()
            with col_cancel:
                if st.button("Cancel", key=f"cancel-btn-{msg_id}"):
                    st.session_state.edit_message_id = None
                    st.session_state.edit_message_content = ""
                    st.rerun()
        else:
            if msg_type == "text":
                st.write(content)
            elif msg_type == "image" and file_path:
                st.image(file_path)
            elif msg_type == "file" and file_path:
                with open(file_path, "rb") as f:
                    st.download_button("Download File", data=f.read(), file_name=os.path.basename(file_path))
            elif msg_type == "voice" and file_path:
                st.audio(file_path)

            # Edit button for user's last message and text only
            if user == st.session_state.username and msg_id == last_user_msg_id and msg_type == "text":
                if st.button("Edit", key=f"edit-btn-{msg_id}"):
                    st.session_state.edit_message_id = msg_id
                    st.session_state.edit_message_content = content
                    st.rerun()

        # Reply button
        if st.button("Reply", key=f"reply-{msg_id}"):
            st.session_state.reply_to = msg_id
            st.rerun()

        # Like/unlike feature
        liked_users = get_likes_for_message(msg_id)
        current_user_liked = st.session_state.username in liked_users

        like_label = "Unlike ❤️" if current_user_liked else "Like 🤍"
        col_like, col_users = st.columns([1, 5])

        with col_like:
            if st.button(like_label, key=f"like-btn-{msg_id}"):
                if current_user_liked:
                    remove_like(st.session_state.username, msg_id)
                else:
                    add_like(st.session_state.username, msg_id)
                st.rerun()

        with col_users:
            if liked_users:
                max_show = 5
                shown_users = list(liked_users)[:max_show]
                display_names = ", ".join(shown_users)
                if len(liked_users) > max_show:
                    display_names += f", and {len(liked_users) - max_show} more"
                st.markdown(f"<small>Liked by: {display_names}</small>", unsafe_allow_html=True)
            else:
                st.markdown("<small>No likes yet</small>", unsafe_allow_html=True)

st.divider()

# Reply preview above input
if st.session_state.get("reply_to"):
    replied_msg = get_message_by_id(st.session_state.reply_to)
    if replied_msg:
        r_id, r_user, r_ts, r_type, r_content, r_file_path, r_recipient, r_reply_to = replied_msg
        preview_text = r_content if r_type == "text" else f"[{r_type.capitalize()} message]"
        st.markdown(f"**Replying to {r_user}:** {preview_text}")
    else:
        st.markdown("**Replying to:** Unknown message")
    if st.button("Cancel Reply"):
        st.session_state.reply_to = None

# Message input
st.subheader("Send a Message")
msg_type = st.selectbox("Message Type", ["text", "image", "file", "voice"], key="msg_type")

def jump_to_latest_page():
    _, total_count = get_messages(
        st.session_state.username,
        active_chat_user,
        search_text=st.session_state.search_text.strip() or None,
        page=1,
        page_size=1,
    )
    last_page = max(1, (total_count + st.session_state.page_size - 1) // st.session_state.page_size)
    st.session_state.page = last_page

reply_to = st.session_state.get("reply_to", None)

if msg_type == "text":
    txt = st.text_area("Message", max_chars=1000)
    if st.button("Send Text") and txt.strip():
        save_message(
            st.session_state.username,
            "text",
            content=txt.strip(),
            recipient=active_chat_user,
            reply_to=reply_to,
        )
        st.session_state.reply_to = None
        jump_to_latest_page()
        st.rerun()

elif msg_type == "image":
    uploaded = st.file_uploader("Upload image (PNG, JPG, JPEG)", type=["png", "jpg", "jpeg"])
    if uploaded and st.button("Send Image"):
        save_message(
            st.session_state.username,
            "image",
            file_bytes=uploaded.read(),
            file_name=uploaded.name,
            recipient=active_chat_user,
            reply_to=reply_to,
        )
        st.session_state.reply_to = None
        jump_to_latest_page()
        st.rerun()

elif msg_type == "file":
    uploaded = st.file_uploader("Upload any file")
    if uploaded and st.button("Send File"):
        save_message(
            st.session_state.username,
            "file",
            file_bytes=uploaded.read(),
            file_name=uploaded.name,
            recipient=active_chat_user,
            reply_to=reply_to,
        )
        st.session_state.reply_to = None
        jump_to_latest_page()
        st.rerun()

elif msg_type == "voice":
    uploaded = st.file_uploader(
        "Upload audio file (WAV, MP3, OGG, M4A, etc.)",
        type=["wav", "mp3", "ogg", "m4a"],
    )
    if uploaded and st.button("Send Audio"):
        save_message(
            st.session_state.username,
            "voice",
            file_bytes=uploaded.read(),
            file_name=uploaded.name,
            recipient=active_chat_user,
            reply_to=reply_to,
        )
        st.session_state.reply_to = None
        jump_to_latest_page()
        st.rerun()
