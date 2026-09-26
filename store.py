from datetime import datetime, timezone


class Store:
    """Временное состояние бота: без файлов, базы данных и сохранения после рестарта."""

    def __init__(self):
        self.users, self.requests, self.selections = {}, {}, set()
        self.next_request_id = 1

    def user(self, uid):
        return self.users.setdefault(uid, {'id': uid, 'stage': 'contact', 'card': None, 'participant': None})

    def update(self, uid, **fields):
        if not fields or not set(fields) <= {'stage', 'card', 'participant'}:
            raise ValueError('Invalid fields')
        self.user(uid).update(fields)

    def create_verification(self, uid, code):
        for request in self.requests.values():
            if request['user_id'] == uid and request['status'] == 'pending':
                request['status'] = 'superseded'
        request_id = self.next_request_id
        self.next_request_id += 1
        self.requests[request_id] = {'id': request_id, 'user_id': uid, 'code': code,
            'status': 'pending', 'created': datetime.now(timezone.utc).isoformat(),
            'reviewed': None, 'reviewer_id': None}
        return request_id

    def review_verification(self, request_id, approved, reviewer_id):
        request = self.requests.get(request_id)
        if not request or request['status'] != 'pending':
            return None
        request['status'] = 'approved' if approved else 'rejected'
        request['reviewed'] = datetime.now(timezone.utc).isoformat()
        request['reviewer_id'] = reviewer_id
        self.update(request['user_id'], stage='ready' if approved else 'code')
        return request

    def select(self, uid, pid):
        self.selections.add((uid, pid))

    def selected(self, uid, pid):
        return (uid, pid) in self.selections
