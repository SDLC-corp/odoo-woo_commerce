import json
import re

import requests

from odoo import _, fields, models
from odoo.exceptions import UserError


class WooAIErrorAssistant(models.AbstractModel):
    _name = "woo.ai.error.assistant"
    _description = "Woo AI Error Assistant"

    _MAX_PROMPT_PAYLOAD_CHARS = 1200
    _MAX_TEXT_CHARS = 4000

    def _mask_sensitive_text(self, value):
        text = str(value or "")
        if not text:
            return ""

        # Mask emails.
        text = re.sub(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", "[masked_email]", text)
        # Mask phone-like values.
        text = re.sub(r"\+?\d[\d\-\s()]{7,}\d", "[masked_phone]", text)
        # Prevent accidental exposure of bearer tokens/api keys in arbitrary strings.
        text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.=+/]+", r"\1[masked_token]", text)
        text = re.sub(r"(?i)(api[_\- ]?key['\"=: ]+)[A-Za-z0-9_\-\.=+/]+", r"\1[masked_token]", text)
        return text

    def _truncate(self, value, limit=None):
        text = str(value or "")
        max_len = int(limit or self._MAX_TEXT_CHARS)
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    def _safe_json_summary(self, raw_payload):
        if not raw_payload:
            return ""
        payload = {}
        try:
            payload = json.loads(raw_payload) if isinstance(raw_payload, str) else (raw_payload or {})
        except Exception:
            return self._truncate(self._mask_sensitive_text(raw_payload), self._MAX_PROMPT_PAYLOAD_CHARS)

        if not isinstance(payload, dict):
            return self._truncate(self._mask_sensitive_text(payload), self._MAX_PROMPT_PAYLOAD_CHARS)

        safe_keys = [
            "id",
            "name",
            "sku",
            "slug",
            "number",
            "status",
            "operation_type",
            "source_action",
            "sync_direction",
            "woo_id",
            "resource",
            "topic",
            "event",
            "currency",
            "total",
            "code",
            "error",
            "message",
            "mode",
            "record_type",
        ]
        summary = {}
        for key in safe_keys:
            if key in payload and payload.get(key) not in (None, False, "", [], {}):
                summary[key] = payload.get(key)

        nested_payload = payload.get("payload")
        if isinstance(nested_payload, dict):
            nested_summary = {}
            for key in safe_keys:
                if key in nested_payload and nested_payload.get(key) not in (None, False, "", [], {}):
                    nested_summary[key] = nested_payload.get(key)
            if nested_summary:
                summary["payload"] = nested_summary

        if not summary:
            keys = list(payload.keys())[:15]
            summary = {"payload_keys": keys}

        text = json.dumps(summary, default=str, ensure_ascii=True)
        text = self._mask_sensitive_text(text)
        return self._truncate(text, self._MAX_PROMPT_PAYLOAD_CHARS)

    def _extract_text_response(self, response_json):
        choices = response_json.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    if isinstance(part.get("text"), str):
                        parts.append(part.get("text"))
                    elif isinstance(part.get("content"), str):
                        parts.append(part.get("content"))
            return "\n".join(parts)
        return ""

    def _strip_fences(self, text):
        value = (text or "").strip()
        if value.startswith("```"):
            lines = value.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            value = "\n".join(lines).strip()
        return value

    def _parse_ai_output(self, raw_text):
        content = self._strip_fences(raw_text)
        explanation = content
        suggested_fix = ""
        retry_recommended = False

        try:
            payload = json.loads(content)
            if isinstance(payload, dict):
                explanation = payload.get("simple_explanation") or payload.get("explanation") or content
                root_cause = payload.get("root_cause") or payload.get("likely_cause") or ""
                fix_steps = payload.get("fix_steps") or payload.get("suggested_fix_steps") or payload.get("suggested_fix") or ""
                technical = payload.get("technical_notes") or payload.get("technical_details") or ""
                retry_value = payload.get("retry_recommended")
                if isinstance(retry_value, bool):
                    retry_recommended = retry_value
                elif isinstance(retry_value, str):
                    retry_recommended = retry_value.strip().lower() in ("yes", "true", "1", "recommended")

                parts = []
                if explanation:
                    parts.append("Explanation:\n%s" % explanation)
                if root_cause:
                    parts.append("Likely Cause:\n%s" % root_cause)
                if technical:
                    parts.append("Technical Notes:\n%s" % technical)
                suggestion_parts = []
                if fix_steps:
                    suggestion_parts.append(str(fix_steps))
                suggestion_parts.append("Retry recommended: %s" % ("Yes" if retry_recommended else "No"))
                suggested_fix = "\n\n".join(suggestion_parts)
                explanation = "\n\n".join(parts) if parts else content
        except Exception:
            lowered = content.lower()
            if "retry recommended: yes" in lowered or "retry recommendation: yes" in lowered:
                retry_recommended = True
            if "suggested fix" in lowered or "fix steps" in lowered:
                suggested_fix = content

        if not suggested_fix:
            suggested_fix = _("Review the explanation and apply the recommended fixes before retry.")

        return {
            "ai_explanation": self._truncate(self._mask_sensitive_text(explanation)),
            "ai_suggested_fix": self._truncate(self._mask_sensitive_text(suggested_fix)),
            "ai_retry_recommended": bool(retry_recommended),
            "ai_last_analyzed_at": fields.Datetime.now(),
        }

    def _build_system_prompt(self):
        return (
            "You are an expert Odoo WooCommerce connector support engineer. "
            "Analyze the failed sync error and provide concise, practical guidance. "
            "Respond in JSON with keys: simple_explanation, root_cause, fix_steps, technical_notes, retry_recommended."
        )

    def _build_report_user_prompt(self, report):
        payload_summary = self._safe_json_summary(report.payload_json)
        safe_data = {
            "record_type": "woo.report",
            "status": report.status,
            "operation": self._mask_sensitive_text(report.operation),
            "operation_type": report.operation_type,
            "source_action": report.source_action,
            "sync_direction": report.sync_direction,
            "woo_id": report.woo_id,
            "message": self._truncate(self._mask_sensitive_text(report.message)),
            "error_message": self._truncate(self._mask_sensitive_text(report.error_message or report.message)),
            "payload_summary": payload_summary,
        }
        return (
            "Analyze this failed sync error and provide:\n"
            "1. Simple explanation\n"
            "2. Root cause\n"
            "3. Fix steps\n"
            "4. Retry recommendation\n"
            "5. Technical notes\n\n"
            f"Data:\n{json.dumps(safe_data, indent=2, default=str)}"
        )

    def _build_webhook_user_prompt(self, webhook_log):
        payload_summary = self._safe_json_summary(webhook_log.payload_json)
        safe_data = {
            "record_type": "woo.webhook.log",
            "status": webhook_log.status,
            "topic": self._mask_sensitive_text(webhook_log.topic),
            "event": self._mask_sensitive_text(webhook_log.event),
            "resource_type": webhook_log.resource_type,
            "source_action": webhook_log.source_action,
            "woo_id": webhook_log.woo_id,
            "error_message": self._truncate(self._mask_sensitive_text(webhook_log.error_message)),
            "payload_summary": payload_summary,
        }
        return (
            "Analyze this failed webhook processing error and provide:\n"
            "1. Simple explanation\n"
            "2. Root cause\n"
            "3. Fix steps\n"
            "4. Retry recommendation\n"
            "5. Technical notes\n\n"
            f"Data:\n{json.dumps(safe_data, indent=2, default=str)}"
        )

    def _build_ai_request(self, instance, user_prompt):
        provider = instance.ai_error_provider or "openai"
        endpoint = (instance.ai_error_endpoint or "https://api.openai.com/v1").strip().rstrip("/")
        api_key = (instance.ai_error_api_key or "").strip()
        model = (instance.ai_error_model or "gpt-4o-mini").strip()

        if provider == "azure_openai":
            base_url = endpoint
            if "/chat/completions" not in base_url:
                base_url = f"{base_url}/chat/completions"
            api_version = (instance.ai_error_api_version or "").strip()
            if api_version and "api-version=" not in base_url:
                join_char = "&" if "?" in base_url else "?"
                base_url = f"{base_url}{join_char}api-version={api_version}"
            headers = {
                "Content-Type": "application/json",
                "api-key": api_key,
            }
        else:
            base_url = endpoint if endpoint.endswith("/chat/completions") else f"{endpoint}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }

        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": self._build_system_prompt()},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": float(instance.ai_error_temperature or 0.2),
            "max_tokens": int(instance.ai_error_max_tokens or 500),
        }
        return base_url, headers, body

    def _check_ai_configuration(self, instance):
        if not instance.ai_error_assistant_enabled:
            raise UserError(_("AI Error Assistant is not configured."))
        if not instance.ai_error_api_key or not instance.ai_error_model:
            raise UserError(_("AI Error Assistant is not configured."))
        if not instance.ai_error_endpoint:
            raise UserError(_("AI Error Assistant is not configured."))

    def _run_ai_analysis(self, instance, user_prompt):
        self._check_ai_configuration(instance)
        url, headers, body = self._build_ai_request(instance, user_prompt)
        timeout_seconds = int(instance.ai_error_timeout_seconds or 20)

        response = requests.post(
            url,
            headers=headers,
            json=body,
            timeout=timeout_seconds,
        )
        if response.status_code >= 400:
            raise ValueError(_("AI provider request failed (HTTP %s).") % response.status_code)
        data = response.json()
        text = self._extract_text_response(data)
        if not text:
            raise ValueError(_("AI provider returned an empty response."))
        return self._parse_ai_output(text)

    def explain_report_error(self, report):
        report.ensure_one()
        if report.status != "failed":
            raise UserError(_("AI explanation is available only for failed sync reports."))
        instance = report.instance_id
        self._check_ai_configuration(instance)
        prompt = self._build_report_user_prompt(report)
        return self._run_ai_analysis(instance, prompt)

    def explain_webhook_error(self, webhook_log):
        webhook_log.ensure_one()
        if webhook_log.status != "failed":
            raise UserError(_("AI explanation is available only for failed webhook logs."))
        instance = webhook_log.instance_id
        if not instance:
            raise UserError(_("AI Error Assistant is not configured."))
        self._check_ai_configuration(instance)
        prompt = self._build_webhook_user_prompt(webhook_log)
        return self._run_ai_analysis(instance, prompt)
