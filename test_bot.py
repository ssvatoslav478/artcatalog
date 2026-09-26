import unittest

from store import Store


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def test_approval_opens_catalog(self):
        self.store.update(101, stage='code')
        request_id = self.store.create_verification(101, '123456')
        request = self.store.review_verification(request_id, True, 900)
        self.assertEqual(request['code'], '123456')
        self.assertEqual(request['user_id'], 101)
        self.assertEqual(self.store.user(101)['stage'], 'ready')
        row = self.store.requests[request_id]
        self.assertEqual((row['status'], row['reviewer_id']), ('approved', 900))

    def test_rejection_allows_retry_and_supersedes_old_request(self):
        self.store.update(101, stage='code')
        first = self.store.create_verification(101, 'first')
        second = self.store.create_verification(101, 'second')
        self.assertEqual(self.store.requests[first]['status'], 'superseded')
        self.assertIsNone(self.store.review_verification(first, True, 900))
        self.assertIsNotNone(self.store.review_verification(second, False, 900))
        self.assertEqual(self.store.user(101)['stage'], 'code')

    def test_duplicate_review_is_ignored(self):
        self.store.update(101, stage='code')
        request_id = self.store.create_verification(101, '123456')
        self.assertIsNotNone(self.store.review_verification(request_id, True, 900))
        self.assertIsNone(self.store.review_verification(request_id, False, 901))


if __name__ == '__main__':
    unittest.main()
