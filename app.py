from flask import Flask, request, jsonify
from flask_cors import CORS
import os, json, requests
from supabase import create_client

app = Flask(__name__)
CORS(app)

SUPABASE_URL=os.environ.get("SUPABASE_URL")
SUPABASE_KEY=os.environ.get("SUPABASE_KEY")
supabase=create_client(SUPABASE_URL, SUPABASE_KEY)

ROLE_MAPPING = {
    "java": {"full_name": "java developer","json_file": "java polished.json"},
    "android": {"full_name": "android developer","json_file": "android.json"}
}
OPENROUTER_KEY=os.environ.get("OPENROUTER_KEY")
def load_json(file_name):
    with open(file_name, "r", encoding="utf-8") as f:
        return json.load(f)
def extract_role(query):
    keywords={"java": ["java"],"android": ["android"]}
    for key, words in keywords.items():
        if any(word in query.lower() for word in words):
            return key
    return None
async def save_to_supabase(table,data):
    supabase.table(table).upsert(data).execute()
async def load_from_supabase(session_id):
    res = supabase.table("sessions").select("session_data").eq("session_id", session_id).execute()
    return res.data[0]["session_data"] if res.data else {"history": []}
async def delete_session(session_id):
    supabase.table("sessions").delete().eq("session_id", session_id).execute()
async def add_to_starred(session_id,session_data):
    supabase.table("starred").upsert({"session_id": session_id, "starred_data": session_data}).execute()
def generate_response(user_query,json_data,role):
    prompt = f"""
You are a helpful assistant for creating Templates as a StackHub AI.
Create a markdown response(must be template form fully markdown) to the user query based on the provided JSON data.
The response should be a template with all proper details and contents for {role}.
## Instructions:
- You **must only reply in valid fully structured Markdown** format.
- The entire response should be a **Markdown-based template** ready to be used as documentation or guide.
- Never include plain text or explanations outside the Markdown content.
- Start your response directly with Markdown headers like `#`, `##`, `###`, etc.
- Use bullet points, code blocks, tables, or other Markdown syntax as needed.
- The goal is to create a structured document-style Markdown template for a **{role}** based on the user query and tool dataset.
- Ensure the response is **well-organized** and **easy to read**.
- **Use the provided JSON data to fill in the details**.

### User Query:
{user_query}

### Tool Dataset(JSON):
```json
{json.dumps(json_data,indent=2)}
"""
    headers={"Authorization": f"Bearer {OPENROUTER_KEY}","HTTP-Referer":"https://stackindai.vercel.app/","X-Title":"Stackind AI"}
    data={"model": "deepseek/deepseek-r1-0528:free","messages": [{"role":"user","content": prompt}],"temperature": 0.7 ,"frequency_penalty": 0.4,"presence_penalty": 0.6}
    try:
        r=requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers,json=data)
        print("DEBUG RESPONSE:", r.status_code, r.text)
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error generating response: {str(e)}"
@app.route("/ask", methods=["POST"])
async def ask():
    raw_query=request.json.get("query","")
    try:
        session_id,query= raw_query.split(" ",1)
    except:
        return jsonify({"error": "Invalid format. Use '<sessionid> job: ...' or '<sessionid> user query: ...'"}), 400
    session_data = await load_from_supabase(session_id)
    if "history" not in session_data:
        session_data["history"] = []
    if query.lower()=="system: delete":
        await delete_session(session_id)
        return jsonify({"status": f"Session '{session_id}' deleted."})
    if query.lower()=="starred":
        await add_to_starred(session_id,session_data)
        return jsonify({"status": f"Session '{session_id}' saved to starred."})
    if query.startswith("job:"):
        role_key = extract_role(query)
        role_info = ROLE_MAPPING.get(role_key)
        if not role_info:
            return jsonify({"session_id":session_id,"answer":"Unsupported role."})
        session_data["json_used"] = role_info["json_file"]
        session_data["history"].append({"query": query, "response": f"Connected to {role_info['full_name']} assistant.","role":role_info['full_name']})
        await save_to_supabase("sessions", {"session_id":session_id, "session_data":session_data})
        return jsonify({"session_id": session_id, "answer": f"Connected to {role_info['full_name']} assistant."})
    if "json_used" not in session_data:
        return jsonify({"error": "No role selected. Start with 'job: ...'"}), 400
    role = next((entry["role"] for entry in reversed(session_data["history"]) if "role" in entry), "User")
    json_data = load_json(session_data["json_used"])
    response = generate_response(query, json_data, role)
    session_data["history"].append({"query": query, "response": response})
    await save_to_supabase("sessions", {"session_id": session_id, "session_data": session_data})
    return jsonify({"session_id": session_id, "answer": response})
@app.route("/history/<session_id>", methods=["GET"])
async def history(session_id):
    session_data = await load_from_supabase(session_id)
    return jsonify({ "session_id": session_id, "history": session_data.get("history", []),"json_used": session_data.get("json_used") })
@app.route("/reset", methods=["POST"])
async def reset():
    supabase.table("sessions").delete().neq("session_id", "NULL").execute()
    return jsonify({"status": "All sessions cleared."})
if __name__ == "__main__":
    app.run(debug=True, port=5000)
