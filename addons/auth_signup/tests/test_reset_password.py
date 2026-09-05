# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.addons.mail.models.mail_mail import MailDeliveryException
from odoo.addons.mail.tests.common import MailCommon
from odoo.tests.common import tagged, HttpCase
from odoo.tools import mute_logger
from werkzeug.urls import url_parse


@tagged('at_install', '-post_install')  # LEGACY at_install
class TestResetPassword(HttpCase, MailCommon):

    @classmethod
    def setUpClass(cls):
        super(TestResetPassword, cls).setUpClass()
        cls.test_user = cls.env['res.users'].create({
            'login': 'test',
            'name': 'The King',
            'email': 'noop@example.com',
        })

    def test_reset_password(self):
        """
            Test that first signup link and password reset link are different to accomodate for the different behaviour
            on first signup if a password is already set user is redirected to login page when accessing that link again
            'signup_email' is used in the web controller (web_auth_reset_password) to detect this behaviour
        """

        self.assertEqual(self.test_user.email, url_parse(self.test_user.with_context(create_user=True).partner_id._get_signup_url()).decode_query()["signup_email"], "query must contain 'signup_email'")

        # Invalidate signup_url to skip signup process
        self.env.invalidate_all()
        self.test_user.action_reset_password()

        self.assertNotIn("signup_email", url_parse(self.test_user.partner_id._get_signup_url()).decode_query(), "query should not contain 'signup_email'")

    @patch('odoo.addons.mail.models.mail_mail.MailMail.send')
    def test_reset_password_mail_server_error(self, mock_send):
        """
        Test that action_reset_password() method raises UserError and _action_reset_password() method raises MailDeliveryException.

        action_reset_password() method attempts to reset the user's password by executing the private method _action_reset_password().
        If any errors occur during the password reset process, a UserError exception is raised with the following behavior:

        - If a MailDeliveryException is caught and the exception's second argument is a ConnectionRefusedError,
        a UserError is raised with the message "Could not contact the mail server, please check your outgoing email server configuration".
        This indicates that the error is related to the mail server and the user should verify their email server settings.

        - If a MailDeliveryException is caught but the exception's second argument is not a ConnectionRefusedError,
        a UserError is raised with the message "There was an error when trying to deliver your Email, please check your configuration".
        This indicates that there was an error during the email delivery process, and the user should review their email configuration.

        Note: The _action_reset_password() method, marked as private with the underscore prefix, performs the actual password reset logic
        and the original MailDeliveryException occurs from this method.
        """

        mock_send.side_effect = MailDeliveryException(
            "Unable to connect to SMTP Server",
            ConnectionRefusedError("111, 'Connection refused'"),
        )
        with self.assertRaises(UserError) as cm1:
            self.test_user.action_reset_password()

        self.assertEqual(
            str(cm1.exception),
            "Could not contact the mail server, please check your outgoing email server configuration",
        )

        mock_send.side_effect = MailDeliveryException(
            "Unable to connect to SMTP Server",
            ValueError("[Errno -2] Name or service not known"),
        )
        with self.assertRaises(UserError) as cm2:
            self.test_user.action_reset_password()

        self.assertEqual(
            str(cm2.exception),
            "There was an error when trying to deliver your Email, please check your configuration",
        )

        # To check private method _action_reset_password() raises MailDeliveryException when there is no valid smtp server
        with self.assertRaises(MailDeliveryException):
            self.test_user._action_reset_password()

    def test_send_password_reset_instructions_to_multiple_users(self):
        """Test that password reset instruction emails are sent to multiple users."""
        test_user2 = self.env['res.users'].create({
            'login': 'test2',
            'name': 'Test 2',
            'email': 'test@example.com',
        })

        with self.mock_mail_gateway():
            self.assertFalse(self._new_mails)
            (self.test_user | test_user2).action_reset_password()

        self.assertEqual(len(self._new_mails), 2)

    def _post_reset_password(self, login):
        self.authenticate(None, None)
        return self.url_open('/web/reset_password', data={
            'login': login,
            'csrf_token': self.csrf_token(),
        })

    def test_reset_password_generic_response(self):
        """ By default, the public reset password page must not reveal whether
            an account exists for the submitted login: the response is the
            same for a known and an unknown login, and no error is shown.
        """
        self.env['ir.config_parameter'].sudo().set_bool('auth_signup.default_reset_password_response', False)
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
            self.assertNotIn('No account found for this login', response.text)
            self.assertNotIn('Password reset instructions sent to your email address.', response.text)

        # the known user did get a reset token
        self.assertEqual(self.test_user.partner_id.signup_type, 'reset')

    def test_reset_password_generic_response_hides_delivery_errors(self):
        """ Mail delivery errors only happen for existing accounts, so they must
            not be surfaced either when the generic response is enabled.
        """
        self.env['ir.config_parameter'].sudo().set_bool('auth_signup.default_reset_password_response', False)

        with patch('odoo.addons.mail.models.mail_mail.MailMail.send') as mock_send:
            mock_send.side_effect = MailDeliveryException(
                "Unable to connect to SMTP Server",
                ConnectionRefusedError("111, 'Connection refused'"),
            )
            response = self._post_reset_password(self.test_user.login)

        self.assertEqual(response.status_code, 200)
        self.assertIn("If there is an account associated with this login", response.text)
        self.assertNotIn('alert-danger', response.text)
        self.assertNotIn('Could not contact the mail server', response.text)

    def test_reset_password_default_odoo_response(self):
        """ With auth_signup.default_reset_password_response enabled, Odoo's
            default behaviour is kept: unknown logins get an explicit error.
        """
        self.env['ir.config_parameter'].sudo().set_str('auth_signup.default_reset_password_response', '1')

        with patch('odoo.addons.mail.models.mail_mail.MailMail.send'):
            response_known = self._post_reset_password(self.test_user.login)
            response_unknown = self._post_reset_password('nobody@example.com')

        self.assertEqual(response_known.status_code, 200)
        self.assertIn('Password reset instructions sent to your email address.', response_known.text)
        self.assertNotIn('alert-danger', response_known.text)

        self.assertEqual(response_unknown.status_code, 200)
        self.assertIn('No account found for this login', response_unknown.text)
        self.assertNotIn('If there is an account associated with this login', response_unknown.text)

    def test_use_default_reset_password_response_param(self):
        """ The config parameter accepts the usual truthy/falsy spellings and
            defaults to the generic (non-revealing) behaviour.
        """
        Users = self.env['res.users']
        ICP = self.env['ir.config_parameter'].sudo()
        key = 'auth_signup.default_reset_password_response'
        ICP.set_bool(key, False)
        self.assertFalse(Users._use_default_reset_password_response())
        ICP.set_bool(key, True)
        self.assertTrue(Users._use_default_reset_password_response())
        # values set as plain strings (e.g. from the technical menu) are parsed too
        for value in ('1', 'True', 'true'):
            ICP.set_str(key, value)
            self.assertTrue(Users._use_default_reset_password_response(), value)
        for value in ('0', 'False', 'false'):
            ICP.set_str(key, value)
            self.assertFalse(Users._use_default_reset_password_response(), value)
        with mute_logger('odoo.addons.base.models.ir_config_parameter'):
            ICP.set_str(key, 'garbage')
            self.assertFalse(Users._use_default_reset_password_response(), 'garbage')
