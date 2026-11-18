"""
Firebase Cloud Messaging (FCM) Integration Provider.
Handles push notification dispatches to Android, iOS, and Web clients.
Gracefully operates in mock/fallback mode when credentials are not configured or in testing environments.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings

logger = logging.getLogger(__name__)

# Try importing firebase_admin; fallback gracefully if not installed
try:
    import firebase_admin
    from firebase_admin import credentials, messaging
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    firebase_admin = None
    credentials = None
    messaging = None


class FCMNotificationResult:
    def __init__(
        self,
        success_count: int = 0,
        failure_count: int = 0,
        failed_tokens: Optional[List[str]] = None,
        deactivated_tokens: Optional[List[str]] = None,
        dry_run: bool = False,
    ):
        self.success_count = success_count
        self.failure_count = failure_count
        self.failed_tokens = failed_tokens or []
        self.deactivated_tokens = deactivated_tokens or []
        self.dry_run = dry_run

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "failed_tokens": self.failed_tokens,
            "deactivated_tokens": self.deactivated_tokens,
            "dry_run": self.dry_run,
        }


class FCMClient:
    """
    Client for interacting with Firebase Cloud Messaging (FCM).
    """

    _app_initialized = False

    @classmethod
    def _initialize_app(cls) -> bool:
        """Initializes Firebase Admin default app once if credentials are provided."""
        if not FIREBASE_AVAILABLE:
            return False

        if cls._app_initialized or len(firebase_admin._apps) > 0:
            cls._app_initialized = True
            return True

        cred_path = getattr(settings, "FIREBASE_CREDENTIALS_PATH", "")
        project_id = getattr(settings, "FIREBASE_PROJECT_ID", "")

        try:
            if cred_path:
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
            elif project_id:
                cred = credentials.ApplicationDefault()
                firebase_admin.initialize_app(cred, {"projectId": project_id})
            else:
                # No credentials provided; dry-run/mock mode
                return False

            cls._app_initialized = True
            logger.info("Firebase Admin SDK initialized successfully.")
            return True
        except Exception as exc:
            logger.warning(f"Firebase Admin SDK initialization skipped or failed: {exc}")
            return False

    @classmethod
    def send_multicast(
        cls,
        tokens: List[str],
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        high_priority: bool = True,
        dry_run: bool = False,
    ) -> FCMNotificationResult:
        """
        Sends a multicast push notification to multiple FCM registration tokens.
        Identifies unregistered/invalid tokens for subsequent deactivation.
        """
        if not tokens:
            return FCMNotificationResult(success_count=0, failure_count=0)

        # Sanitize data payload (FCM data message values must all be strings)
        sanitized_data: Dict[str, str] = {}
        if data:
            for k, v in data.items():
                if isinstance(v, (dict, list)):
                    sanitized_data[str(k)] = json.dumps(v)
                elif v is not None:
                    sanitized_data[str(k)] = str(v)

        is_initialized = cls._initialize_app()

        if not is_initialized or not FIREBASE_AVAILABLE or dry_run:
            logger.info(
                f"[FCM Dry-Run] Dispatching notification to {len(tokens)} token(s). "
                f"Title='{title}', Body='{body}', Data={sanitized_data}"
            )
            return FCMNotificationResult(
                success_count=len(tokens),
                failure_count=0,
                dry_run=True,
            )

        try:
            android_config = messaging.AndroidConfig(
                priority="high" if high_priority else "normal",
                notification=messaging.AndroidNotification(
                    title=title,
                    body=body,
                    sound="default",
                    channel_id="manygym_notifications",
                ),
            )
            apns_config = messaging.ApnsConfig(
                payload=messaging.ApnsPayload(
                    aps=messaging.Aps(
                        sound="default",
                        badge=1,
                    )
                )
            )

            webpush_config = messaging.WebpushConfig(
                notification=messaging.WebpushNotification(
                    title=title,
                    body=body,
                ),
                data=sanitized_data,
            )

            message = messaging.MulticastMessage(
                tokens=tokens,
                notification=messaging.Notification(title=title, body=body),
                data=sanitized_data,
                android=android_config,
                apns=apns_config,
                webpush=webpush_config,
            )

            response = messaging.send_each_for_multicast(message)

            failed_tokens: List[str] = []
            deactivated_tokens: List[str] = []

            for idx, resp in enumerate(response.responses):
                if not resp.success:
                    token = tokens[idx]
                    failed_tokens.append(token)
                    err_code = getattr(resp.exception, "code", "")
                    # UNREGISTERED or INVALID_ARGUMENT indicates token is dead
                    if "registration-token-not-registered" in str(err_code).lower() or "unregistered" in str(resp.exception).lower():
                        deactivated_tokens.append(token)

            return FCMNotificationResult(
                success_count=response.success_count,
                failure_count=response.failure_count,
                failed_tokens=failed_tokens,
                deactivated_tokens=deactivated_tokens,
                dry_run=False,
            )

        except Exception as exc:
            logger.error(f"FCM multicast dispatch failed: {exc}", exc_info=True)
            return FCMNotificationResult(
                success_count=0,
                failure_count=len(tokens),
                failed_tokens=tokens,
                dry_run=False,
            )

    @classmethod
    def send_single(
        cls,
        token: str,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        high_priority: bool = True,
    ) -> bool:
        """Sends a push notification to a single FCM device token."""
        result = cls.send_multicast(
            tokens=[token],
            title=title,
            body=body,
            data=data,
            high_priority=high_priority,
        )
        return result.success_count > 0
