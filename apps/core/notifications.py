import json
import urllib.request
import urllib.error
import threading

EXPO_PUSH_URL = 'https://exp.host/--/api/v2/push/send'

def notify_user(user, title, message, notif_type='SYSTEM', data=None):
    """Create a Notification row (read by the in-app bell) and, if the user
    has registered a push token, send a push asynchronously with a timeout."""
    if not user:
        return
    from apps.core.models import Notification
    try:
        Notification.objects.create(user=user, title=title, message=message, type=notif_type)
    except Exception as e:
        print(f"Failed to create Notification row: {e}")

    token = getattr(user, 'expo_push_token', None)
    if token:
        try:
            threading.Thread(
                target=send_expo_push_notification,
                args=(token, title, message, data),
                daemon=True
            ).start()
        except Exception as e:
            print(f"Failed to start push notification thread: {e}")

def send_expo_push_notification(token, title, body, data=None):
    if not token or not token.startswith("ExponentPushToken"):
        return False
    headers = {
        'Accept': 'application/json',
        'Accept-Encoding': 'gzip, deflate',
        'Content-Type': 'application/json',
    }
    payload = {
        'to': token,
        'title': title,
        'body': body,
    }
    if data:
        payload['data'] = data
    req = urllib.request.Request(
        EXPO_PUSH_URL,
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST'
    )
    try:
        response = urllib.request.urlopen(req, timeout=3)
        response_data = json.loads(response.read().decode('utf-8'))
        return True
    except Exception as e:
        print(f"Failed to send Expo push notification: {e}")
        return False
