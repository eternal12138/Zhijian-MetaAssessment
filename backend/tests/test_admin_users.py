import unittest

from pydantic import ValidationError

from app.api.admin import (
    StudentClassAssignmentRequest,
    UserAdminCreate,
    _user_class_fields,
)


class AdminUserClassTests(unittest.TestCase):
    def test_student_class_is_trimmed_and_stored_as_class_group(self):
        payload = UserAdminCreate(
            username=" 2026001 ",
            name=" 张三 ",
            role="student",
            class_group=" 2026级1班 ",
        )

        self.assertEqual(payload.username, "2026001")
        self.assertEqual(payload.name, "张三")
        self.assertEqual(
            _user_class_fields(payload),
            ("2026级1班", None),
        )

    def test_student_can_be_created_without_class_for_later_assignment(self):
        payload = UserAdminCreate(
            username="2026002",
            name="李四",
            role="student",
        )

        self.assertEqual(_user_class_fields(payload), (None, None))

    def test_teacher_classes_are_normalized_and_deduplicated(self):
        payload = UserAdminCreate(
            username="t001",
            name="王老师",
            role="teacher",
            managed_classes="2026级1班 | 2026级2班；2026级1班",
        )

        self.assertEqual(
            _user_class_fields(payload),
            (None, "2026级1班,2026级2班"),
        )

    def test_teacher_can_be_created_without_class_for_later_assignment(self):
        payload = UserAdminCreate(
            username="t003",
            name="赵老师",
            role="teacher",
        )

        self.assertEqual(_user_class_fields(payload), (None, None))

    def test_legacy_teacher_class_group_is_used_as_managed_class(self):
        payload = UserAdminCreate(
            username="t002",
            name="李老师",
            role="teacher",
            class_group="2026级3班",
        )

        self.assertEqual(
            _user_class_fields(payload),
            (None, "2026级3班"),
        )

    def test_admin_does_not_receive_class_scope(self):
        payload = UserAdminCreate(
            username="admin2",
            name="管理员",
            role="admin",
            class_group="2026级1班",
            managed_classes="2026级2班",
        )

        self.assertEqual(_user_class_fields(payload), (None, None))

    def test_student_class_assignment_is_trimmed(self):
        payload = StudentClassAssignmentRequest(class_group=" 2026级4班 ")

        self.assertEqual(payload.class_group, "2026级4班")

    def test_student_class_assignment_rejects_blank_class(self):
        with self.assertRaises(ValidationError):
            StudentClassAssignmentRequest(class_group="   ")


if __name__ == "__main__":
    unittest.main()
