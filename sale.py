#This file is part of Tryton.  The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.
from trytond.model import fields
from trytond.pyson import Eval
from trytond.transaction import Transaction
from trytond.pool import Pool, PoolMeta

__all__ = ['SaleLine', 'Account']
__metaclass__ = PoolMeta


class SaleLine:
    __name__ = 'sale.line'
    analytic_accounts = fields.Many2One('analytic_account.account.selection',
        'Analytic Accounts',
        states={
            'invisible': Eval('type') != 'line',
            },
        depends=['type'])

    @classmethod
    def _view_look_dom_arch(cls, tree, type, field_children=None):
        AnalyticAccount = Pool().get('analytic_account.account')
        AnalyticAccount.convert_view(tree)
        arch, fields, = super(SaleLine, cls)._view_look_dom_arch(tree, type,
            field_children=field_children)
        return arch, fields

    @classmethod
    def fields_get(cls, fields_names=None):
        AnalyticAccount = Pool().get('analytic_account.account')

        res = super(SaleLine, cls).fields_get(fields_names)

        analytic_accounts_field = super(SaleLine, cls).fields_get(
                ['analytic_accounts'])['analytic_accounts']

        res.update(AnalyticAccount.analytic_accounts_fields_get(
                analytic_accounts_field, fields_names,
                states=cls.analytic_accounts.states,
                required_states=Eval('type') == 'line'))
        return res

    @classmethod
    def default_get(cls, fields, with_rec_name=True):
        fields = [x for x in fields if not x.startswith('analytic_account_')]
        return super(SaleLine, cls).default_get(fields,
            with_rec_name=with_rec_name)

    @classmethod
    def read(cls, ids, fields_names=None):
        if fields_names:
            fields_names2 = [x for x in fields_names
                    if not x.startswith('analytic_account_')]
        else:
            fields_names2 = fields_names

        res = super(SaleLine, cls).read(ids, fields_names=fields_names2)

        if not fields_names:
            fields_names = cls._fields.keys()

        root_ids = []
        for field in fields_names:
            if field.startswith('analytic_account_') and '.' not in field:
                root_ids.append(int(field[len('analytic_account_'):]))
        if root_ids:
            id2record = {}
            for record in res:
                id2record[record['id']] = record
            lines = cls.browse(ids)
            for line in lines:
                for root_id in root_ids:
                    id2record[line.id]['analytic_account_'
                        + str(root_id)] = None
                if line.type != 'line':
                    continue
                if not line.analytic_accounts:
                    continue
                for account in line.analytic_accounts.accounts:
                    if account.root.id in root_ids:
                        id2record[line.id]['analytic_account_'
                            + str(account.root.id)] = account.id
                        for field in fields_names:
                            if field.startswith('analytic_account_'
                                    + str(account.root.id) + '.'):
                                ham, field2 = field.split('.', 1)
                                id2record[line.id][field] = account[field2]
        return res

    @classmethod
    def create(cls, vlist):
        Selection = Pool().get('analytic_account.account.selection')
        vlist = [x.copy() for x in vlist]
        for vals in vlist:
            selection_vals = {}
            for field in vals.keys():
                if field.startswith('analytic_account_'):
                    if vals[field]:
                        selection_vals.setdefault('accounts', [])
                        selection_vals['accounts'].append(('add',
                                [vals[field]]))
                    del vals[field]
            if vals.get('analytic_accounts'):
                Selection.write([Selection(vals['analytic_accounts'])],
                    selection_vals)
            elif vals.get('type', 'line') == 'line':
                selection, = Selection.create([selection_vals])
                vals['analytic_accounts'] = selection.id
        return super(SaleLine, cls).create(vlist)

    @classmethod
    def write(cls, *args):
        Selection = Pool().get('analytic_account.account.selection')

        actions = iter(args)
        args = []
        for lines, values in zip(actions, actions):
            values = values.copy()
            selection_vals = {}
            for field, value in values.items():
                if field.startswith('analytic_account_'):
                    root_id = int(field[len('analytic_account_'):])
                    selection_vals[root_id] = value
                    del values[field]
            if selection_vals:
                for line in lines:
                    if line.type != 'line':
                        continue
                    accounts = []
                    if not line.analytic_accounts:
                        # Create missing selection
                        with Transaction().set_user(0):
                            selection, = Selection.create([{}])
                        cls.write([line], {
                            'analytic_accounts': selection.id,
                            })
                    for account in line.analytic_accounts.accounts:
                        if account.root.id in selection_vals:
                            value = selection_vals[account.root.id]
                            if value:
                                accounts.append(value)
                        else:
                            accounts.append(account.id)
                    for account_id in selection_vals.values():
                        if account_id \
                                and account_id not in accounts:
                            accounts.append(account_id)
                    Selection.write([line.analytic_accounts], {
                        'accounts': [('set', accounts)],
                        })
            args.extend((lines, values))
        return super(SaleLine, cls).write(*args)

    @classmethod
    def delete(cls, lines):
        Selection = Pool().get('analytic_account.account.selection')

        selections = []
        for line in lines:
            if line.analytic_accounts:
                selections.append(line.analytic_accounts)

        super(SaleLine, cls).delete(lines)
        Selection.delete(selections)

    @classmethod
    def copy(cls, lines, default=None):
        Selection = Pool().get('analytic_account.account.selection')

        new_lines = super(SaleLine, cls).copy(lines, default=default)

        for line in new_lines:
            if line.analytic_accounts:
                selection, = Selection.copy([line.analytic_accounts])
                cls.write([line], {
                    'analytic_accounts': selection.id,
                    })
        return new_lines

    def get_invoice_line(self, invoice_type):
        AccountSelection = Pool().get('analytic_account.account.selection')

        invoice_lines = super(SaleLine, self).get_invoice_line(invoice_type)
        if not invoice_lines:
            return invoice_lines

        selection = None
        if self.analytic_accounts:
            selection, = AccountSelection.copy([self.analytic_accounts])
        for invoice_line in invoice_lines:
            invoice_line.analytic_accounts = selection
        return invoice_lines


class Account:
    __name__ = 'analytic_account.account'

    @classmethod
    def delete(cls, accounts):
        SaleLine = Pool().get('sale.line')
        super(Account, cls).delete(accounts)
        # Restart the cache on the fields_view_get method of sale.line
        SaleLine._fields_view_get_cache.clear()

    @classmethod
    def create(cls, vlist):
        SaleLine = Pool().get('sale.line')
        accounts = super(Account, cls).create(vlist)
        # Restart the cache on the fields_view_get method of sale.line
        SaleLine._fields_view_get_cache.clear()
        return accounts

    @classmethod
    def write(cls, accounts, values, *args):
        SaleLine = Pool().get('sale.line')
        super(Account, cls).write(accounts, values, *args)
        # Restart the cache on the fields_view_get method of sale.line
        SaleLine._fields_view_get_cache.clear()
