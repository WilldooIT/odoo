# -*- coding: utf-8 -*-
from odoo.tests import common


class TestComputeSql(common.TransactionCase):
    """Coverage for the native ``Field.compute_sql`` attribute.

    A non-stored computed field may declare ``compute_sql`` -- a method that
    returns a per-row :class:`~odoo.tools.SQL` expression. When the field is
    used in a read_group aggregate/groupby, a search domain, or an ORDER BY,
    the ORM converts it via ``Field.to_sql``, which calls the compute_sql
    method with ``(alias, query)``. The ``query`` argument lets the method add
    joins, so a compute_sql field can reference other tables.
    """

    def agg_test_data(self):
        Model = self.env['test_read_group.aggregate']
        partner_1 = self.env['res.partner'].create({'name': 'z_one'})
        partner_2 = self.env['res.partner'].create({'name': 'a_two'})
        Model.create({'key': 1, 'partner_id': partner_1.id, 'value': 1})
        Model.create({'key': 1, 'partner_id': partner_1.id, 'value': 2})
        Model.create({'key': 1, 'partner_id': partner_2.id, 'value': 3})
        Model.create({'key': 2, 'partner_id': partner_2.id, 'value': 4})
        Model.create({'key': 2, 'partner_id': partner_2.id})
        Model.create({'key': 2, 'value': 5})
        Model.create({'partner_id': partner_2.id, 'value': 5})
        Model.create({'value': 6})
        Model.create({})

    def test_basic(self):
        # Per-row arithmetic (value*2) wrapped by the standard SUM aggregator.
        self.agg_test_data()

        Model = self.env['test_read_group.aggregate']
        field_name = 'value_doubled_sql'

        ungrouped = sum(Model.search([]).mapped(field_name))
        self.assertEqual(ungrouped, 2 * (1 + 2 + 3 + 4 + 0 + 5 + 5 + 6 + 0))

        self.assertEqual(
            Model._read_group([], groupby=['key'], aggregates=[f'{field_name}:sum']),
            [
                (1, 2 * (1 + 2 + 3)),
                (2, 2 * (4 + 5)),
                (False, 2 * (5 + 6)),
            ],
        )

    def test_with_join(self):
        # Exercises Query.add_join / Query.make_alias from inside the
        # compute_sql method -- this only works because ``query`` is threaded
        # into to_sql. Both fixture partners have name length 5.
        self.agg_test_data()

        Model = self.env['test_read_group.aggregate']
        field_name = 'value_x_partner_name_len_sql'

        # Records with partners (1,2,3 under key=1; 4,5 under key=2; 7 under
        # key=False) get value*5; records without partners contribute 0.
        # The key=2 record with a partner but value=0 (default) contributes 0.
        self.assertEqual(
            Model._read_group([], groupby=['key'], aggregates=[f'{field_name}:sum']),
            [
                (1, 5 * (1 + 2 + 3)),
                (2, 5 * 4),
                (False, 5 * 5),
            ],
        )

        ungrouped = sum(Model.search([]).mapped(field_name))
        self.assertEqual(ungrouped, 5 * (1 + 2 + 3) + 5 * 4 + 5 * 5)

    def test_in_search(self):
        # to_sql also fires when the field appears in a search domain.
        # Records with value*2 > 6 have value > 3.
        self.agg_test_data()

        Model = self.env['test_read_group.aggregate']
        matches = Model.search([('value_doubled_sql', '>', 6)])

        self.assertEqual(
            sorted(matches.mapped('value')),
            [4, 5, 5, 6],
        )

    def test_in_order(self):
        # to_sql fires when the field appears in ORDER BY. PostgreSQL NULLS
        # FIRST is the default for DESC, so the two fixture records without a
        # value (NULL in DB, mapped to 0 by Odoo) appear before the non-null
        # values.
        self.agg_test_data()

        Model = self.env['test_read_group.aggregate']
        ordered_values = Model.search([], order='value_doubled_sql desc, id').mapped(
            'value'
        )

        non_null = [v for v in ordered_values if v > 0]
        null_count = len(ordered_values) - len(non_null)
        self.assertTrue(all(v == 0 for v in ordered_values[:null_count]))
        self.assertEqual(non_null, sorted(non_null, reverse=True))

    def test_default_order(self):
        # to_sql fires when a compute_sql field is the model's _order. Uses a
        # dedicated model with _order = "value_doubled_sql asc, id".
        Model = self.env['test_read_group.aggregate_ordered']
        Model.create({'value': 3})
        Model.create({'value': 1})
        Model.create({'value': 2})

        ordered_values = Model.search([]).mapped('value')
        non_null = [v for v in ordered_values if v > 0]
        self.assertEqual(non_null, [1, 2, 3])

    def test_in_groupby(self):
        # to_sql fires when the field appears in groupby, not just aggregates.
        # Records group by the computed expression value.
        self.agg_test_data()

        Model = self.env['test_read_group.aggregate']
        # value_doubled_sql = value * 2. Counts: value=0 -> 2 records,
        # value=1 -> 1, value=2 -> 1, value=3 -> 1, value=4 -> 1,
        # value=5 -> 2, value=6 -> 1.
        rows = Model._read_group(
            [],
            groupby=['value_doubled_sql'],
            aggregates=['__count'],
        )
        result = {doubled: count for doubled, count in rows}
        self.assertEqual(result[0], 2)  # two records with value=0
        self.assertEqual(result[2], 1)  # one record with value=1
        self.assertEqual(result[10], 2)  # two records with value=5

    def test_formatted_read_group(self):
        # Per-row value*2 wrapped in the standard SUM aggregator via the
        # formatted_read_group path.
        self.agg_test_data()

        Model = self.env['test_read_group.aggregate']
        field_name = 'value_doubled_sql'

        self.assertEqual(
            Model.formatted_read_group(
                [], groupby=['key'], aggregates=[f'{field_name}:sum']
            ),
            [
                {
                    '__extra_domain': [('key', '=', 1)],
                    'key': 1,
                    f'{field_name}:sum': 2 * (1 + 2 + 3),
                },
                {
                    '__extra_domain': [('key', '=', 2)],
                    'key': 2,
                    f'{field_name}:sum': 2 * (4 + 5),
                },
                {
                    '__extra_domain': [('key', '=', False)],
                    'key': False,
                    f'{field_name}:sum': 2 * (5 + 6),
                },
            ],
        )
