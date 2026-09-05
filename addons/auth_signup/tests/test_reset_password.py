# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
from unittest.mock import patch

from odoo import http
from odoo.addons.base.models.ir_mail_server import MailDeliveryException
from odoo.tests.common import HttpCase


class TestResetPassword(HttpCase):

    def setUp(self):
        super().setUp()
        # HttpCase has no class-level environment on 14.0
        self.test_user = self.env['res.users'].create({
            'login': 'test',
            'name': 'The King',
            'email': 'noop@example.com',
        })

    def _post_reset_password(self, login):
        self.authenticate(None, None)
        return self.url_open('/web/reset_password', data={
            'login': login,
            'csrf_token': http.WebRequest.csrf_token(self),
        })

    def test_reset_password_generic_response(self):
        """ By default, the public reset password page must not reveal whether
            an account exists for the submitted login: the response is the
            same for a known and an unknown login, and no error is shown.
        """
        self.env['ir.config_parameter'].sudo().set_param('auth_signup.default_reset_password_response', False)
        generic_message = "If there is an account associated with this login, you will receive a password reset link by email."

        with patch('odoo.addons.mail.models.mail_mail.MailMail.send') as mock_send:
            response_known = self._post_reset_password(self.test_user.login)
            self.assertTrue(mock_send.called, "The existing user must receive their password reset link")
            mock_send.reset_mock()
            response_unknown = self._post_reset_password('nobody@example.com')
            self.assertFalse(mock_send.called, "No mail must be sent for an unknown login")

        for response in (response_known, response_unknown):
            self.assertEqual(response.status_code, 200)
            self.assertIn(generic_message, response.text)
            self.assertNotIn('alert-danger', response.text)
            self.assertNotIn('Reset password: invalid username or email', response.text)
            self.assertNotIn('An email has been sent with credentials to reset your password', response.text)

        # the known user did get a reset token
        self.assertEqual(self.test_user.partner_id.signup_type, 'reset')

    def test_reset_password_generic_response_hides_delivery_errors(self):
        """ Mail delivery errors only happen for existing accounts, so they must
            not be surfaced either when the generic response is enabled.
        """
        self.env['ir.config_parameter'].sudo().set_param('auth_signup.default_reset_password_response', False)

        with patch('odoo.addons.mail.models.mail_mail.MailMail.send') as mock_send:
            mock_send.side_effect = MailDeliveryException(
                "Unable to connect to SMTP Server",
                ConnectionRefusedError("111, 'Connection refused'"),
            )
            response = self._post_reset_password(self.test_user.login)

        self.assertEqual(response.status_code, 200)
        self.assertIn("If there is an account associated with this login", response.text)
        self.assertNotIn('alert-danger', response.text)
        self.assertNotIn('Unable to connect to SMTP Server', response.text)

    def test_reset_password_default_odoo_response(self):
        """ With auth_signup.default_reset_password_response enabled, Odoo's
            default behaviour is kept: unknown logins get an explicit error.
        """
        self.env['ir.config_parameter'].sudo().set_param('auth_signup.default_reset_password_response', '1')

        with patch('odoo.addons.mail.models.mail_mail.MailMail.send'):
            response_known = self._post_reset_password(self.test_user.login)
            response_unknown = self._post_reset_password('nobody@example.com')

        self.assertEqual(response_known.status_code, 200)
        self.assertIn('An email has been sent with credentials to reset your password', response_known.text)
        self.assertNotIn('alert-danger', response_known.text)

        self.assertEqual(response_unknown.status_code, 200)
        self.assertIn('Reset password: invalid username or email', response_unknown.text)
        self.assertNotIn('If there is an account associated with this login', response_unknown.text)

    def test_use_default_reset_password_response_param(self):
        """ The config parameter accepts the usual truthy/falsy spellings and
            defaults to the generic (non-revealing) behaviour.
        """
        Users = self.env['res.users']
        set_param = self.env['ir.config_parameter'].sudo().set_param
        set_param('auth_signup.default_reset_password_response', False)
        self.assertFalse(Users._use_default_reset_password_response())
        for value in ('1', 'True', 'true'):
            set_param('auth_signup.default_reset_password_response', value)
            self.assertTrue(Users._use_default_reset_password_response(), value)
        for value in ('0', 'False', 'false', 'garbage'):
            set_param('auth_signup.default_reset_password_response', value)
            self.assertFalse(Users._use_default_reset_password_response(), value)
