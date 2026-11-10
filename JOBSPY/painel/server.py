#!/usr/bin/env python3
"""Painel visual das vagas do JobSpy, com rascunho do Grok e envio do currículo."""

import base64
import json
import re
import smtplib
import subprocess
import traceback
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import urlopen

HOST = "0.0.0.0"
PORT = 4080
JOBS_API = "http://127.0.0.1:4000"
GROK = "/usr/local/bin/grok"
DATA = Path("/home/giovanna/.jobspy-painel")
ROOT = Path(__file__).resolve().parent
PROFILE_PATH = DATA / "profile.json"
CV_PATH = DATA / "curriculo"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
MAX_BODY = 8_000_000
SCHEMA = (
    '{"type":"object","properties":{"subject":{"type":"string"},'
    '"body":{"type":"string"}},"required":["subject","body"],'
    '"additionalProperties":false}'
)


def load_profile():
    if not PROFILE_PATH.exists():
        return {}
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def save_profile(profile):
    DATA.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    PROFILE_PATH.chmod(0o600)


def public_profile(profile):
    cv_name = profile.get("cv_name") if CV_PATH.exists() else None
    return {
        "name": profile.get("name") or "",
        "email": profile.get("email") or "",
        "summary": profile.get("summary") or "",
        "smtp_host": profile.get("smtp_host") or "",
        "smtp_port": int(profile.get("smtp_port") or 587),
        "smtp_user": profile.get("smtp_user") or "",
        "smtp_password_set": bool(profile.get("smtp_password")),
        "cv_name": cv_name or "",
        "cv_ready": CV_PATH.exists() and bool(cv_name),
    }


def extract_emails(value):
    found = []
    if value is None:
        return found
    if isinstance(value, (list, tuple)):
        for item in value:
            found.extend(extract_emails(item))
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(extract_emails(item))
    else:
        found.extend(EMAIL_RE.findall(str(value)))
    unique = []
    for email in found:
        lowered = email.strip()
        if lowered and lowered not in unique:
            unique.append(lowered)
    return unique


def parse_grok(stdout):
    text = stdout.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise RuntimeError("O Grok não devolveu JSON.")
    payload = json.loads(text[start : end + 1])
    structured = payload.get("structuredOutput") if isinstance(payload, dict) else None
    if isinstance(structured, dict) and structured.get("subject") and structured.get("body"):
        return structured["subject"].strip(), structured["body"].strip()
    inner = payload.get("text") if isinstance(payload, dict) else None
    if isinstance(inner, str):
        inner_json = json.loads(inner)
        return inner_json["subject"].strip(), inner_json["body"].strip()
    if isinstance(payload, dict) and payload.get("subject") and payload.get("body"):
        return payload["subject"].strip(), payload["body"].strip()
    raise RuntimeError("A resposta do Grok não trouxe assunto e corpo.")


def draft_with_grok(job, profile):
    description = str(job.get("description") or "").strip()
    if len(description) > 6000:
        description = description[:6000] + "\n[descrição truncada]"
    emails = extract_emails(job.get("emails"))
    prompt = f"""Escreva um e-mail de candidatura em português do Brasil.
Use somente o resumo do candidato. Não invente emprego, tempo de experiência, formação ou ferramenta que não esteja nesse resumo.
Seja direto, cordial e específico para a vaga. O corpo fica em texto puro, com saudação e fecho.
Não inclua o endereço de e-mail do destinatário no corpo.

Candidato: {profile.get("name") or "candidato"}
E-mail do candidato: {profile.get("email") or "não informado"}
Resumo do candidato:
{profile.get("summary")}

Vaga: {job.get("title") or ""}
Empresa: {job.get("company") or ""}
Local: {job.get("location") or ""}
Link: {job.get("job_url_direct") or job.get("job_url") or ""}
E-mails da vaga: {", ".join(emails) if emails else "não informado"}
Descrição:
{description or "não informada"}
"""
    DATA.mkdir(parents=True, exist_ok=True)
    prompt_path = DATA / "prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    try:
        completed = subprocess.run(
            [
                GROK,
                "--prompt-file",
                str(prompt_path),
                "--max-turns",
                "1",
                "--no-subagents",
                "--disable-web-search",
                "--output-format",
                "plain",
                "--json-schema",
                SCHEMA,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=150,
            cwd="/tmp",
        )
    finally:
        prompt_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "falha ao chamar o Grok").strip()
        raise RuntimeError(detail[-1200:])
    return parse_grok(completed.stdout)


def send_mail(profile, recipients, subject, body):
    host = (profile.get("smtp_host") or "").strip()
    user = (profile.get("smtp_user") or "").strip()
    password = profile.get("smtp_password") or ""
    sender = (profile.get("email") or user).strip()
    port = int(profile.get("smtp_port") or 587)
    if not host or not user or not password or not sender:
        raise RuntimeError("Preencha o e-mail e o SMTP antes de enviar.")
    if not CV_PATH.exists():
        raise RuntimeError("Envie o arquivo do currículo antes de mandar a candidatura.")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{profile.get('name')} <{sender}>" if profile.get("name") else sender
    message["To"] = ", ".join(recipients)
    message.set_content(body)
    cv_name = profile.get("cv_name") or "curriculo.pdf"
    subtype = "pdf" if cv_name.lower().endswith(".pdf") else "octet-stream"
    maintype = "application"
    message.add_attachment(
        CV_PATH.read_bytes(),
        maintype=maintype,
        subtype=subtype,
        filename=cv_name,
    )
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
            smtp.login(user, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(user, password)
            smtp.send_message(message)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("O arquivo passou de 8 MB.")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                page = (ROOT / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(page)
                return
            if parsed.path == "/api/status":
                jobs_ok = False
                try:
                    with urlopen(JOBS_API + "/health", timeout=4) as response:
                        jobs_ok = response.status == 200
                except (HTTPError, URLError, TimeoutError):
                    jobs_ok = False
                self.send_json(200, {"jobs_api": jobs_ok, "grok": Path(GROK).exists()})
                return
            if parsed.path == "/api/profile":
                self.send_json(200, public_profile(load_profile()))
                return
            if parsed.path == "/api/jobs":
                query = parsed.query
                url = JOBS_API + "/jobs" + (("?" + query) if query else "")
                with urlopen(url, timeout=180) as response:
                    payload = response.read()
                self.send_response(response.status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            self.send_json(404, {"detail": "Caminho não encontrado."})
        except Exception as error:
            self.send_json(502, {"detail": str(error)})

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            data = self.read_json()
            profile = load_profile()
            if parsed.path == "/api/profile":
                for key in ("name", "email", "summary", "smtp_host", "smtp_user"):
                    if key in data:
                        profile[key] = str(data.get(key) or "").strip()
                if data.get("smtp_port"):
                    profile["smtp_port"] = int(data["smtp_port"])
                if data.get("smtp_password"):
                    profile["smtp_password"] = str(data["smtp_password"])
                save_profile(profile)
                self.send_json(200, public_profile(profile))
                return
            if parsed.path == "/api/cv":
                filename = Path(str(data.get("filename") or "curriculo.pdf")).name
                lowered = filename.lower()
                if not lowered.endswith((".pdf", ".docx", ".txt")):
                    self.send_json(400, {"detail": "Envie um arquivo PDF, DOCX ou TXT."})
                    return
                content = base64.b64decode(data.get("content_base64") or "", validate=True)
                if not content:
                    self.send_json(400, {"detail": "O arquivo do currículo veio vazio."})
                    return
                if lowered.endswith(".pdf") and not content.startswith(b"%PDF"):
                    self.send_json(400, {"detail": "O arquivo não parece um PDF."})
                    return
                DATA.mkdir(parents=True, exist_ok=True)
                CV_PATH.write_bytes(content)
                CV_PATH.chmod(0o600)
                profile["cv_name"] = filename
                save_profile(profile)
                self.send_json(200, public_profile(profile))
                return
            if parsed.path == "/api/draft":
                summary = str(data.get("summary") or profile.get("summary") or "").strip()
                if len(summary) < 40:
                    self.send_json(400, {"detail": "Escreva um resumo profissional de pelo menos algumas linhas antes de gerar o e-mail."})
                    return
                job = data.get("job") or {}
                merged = dict(profile)
                merged["name"] = str(data.get("name") or profile.get("name") or "").strip()
                merged["email"] = str(data.get("email") or profile.get("email") or "").strip()
                merged["summary"] = summary
                subject, body = draft_with_grok(job, merged)
                self.send_json(200, {"subject": subject, "body": body, "emails": extract_emails(job.get("emails"))})
                return
            if parsed.path == "/api/send":
                recipients = extract_emails(data.get("to"))
                subject = str(data.get("subject") or "").strip()
                body = str(data.get("body") or "").strip()
                if not recipients:
                    self.send_json(400, {"detail": "Essa vaga não tem um e-mail válido para envio."})
                    return
                if len(recipients) > 5:
                    self.send_json(400, {"detail": "O envio aceita no máximo 5 destinatários."})
                    return
                if not subject or not body:
                    self.send_json(400, {"detail": "O assunto e o corpo do e-mail são obrigatórios."})
                    return
                send_mail(profile, recipients, subject, body)
                print("candidatura enviada para %s" % ", ".join(recipients), flush=True)
                self.send_json(200, {"sent": True, "to": recipients})
                return
            self.send_json(404, {"detail": "Caminho não encontrado."})
        except Exception as error:
            traceback.print_exc()
            self.send_json(400, {"detail": str(error)})


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("painel em http://%s:%s" % (HOST, PORT), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
