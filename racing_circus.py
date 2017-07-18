#!/usr/bin/python3
# Copyright (C) 2014 Peter Todd <pete@petertodd.org>
#
# This file is subject to the license terms in the LICENSE file found in the
# top-level directory of this distribution.

from enum import Enum
import logging
import math

import bitcoin.rpc
from bitcoin.core import b2x, b2lx, x, lx, str_money_value, COIN, CMutableTransaction, CMutableTxIn, CMutableTxOut
from bitcoin.wallet import CBitcoinAddress

AMOUNT = 0.01  # Amount to send

TESTNET = True
FEE = 0.000011  # Fee-per-KB of payment transaction
RATIO = 2.0  # Ratio of new fee to old fee; default 10x higher

NODES = {
        # No need to split against the original
        # Doing it anyway for a prototype
        'original': {
            'name': 'original (BIP 148)',
            'url': 'http://opssbex:sbex42@127.0.0.1',
            'port': 18332,
            'testnet': True
        },

        # 'segwit2x': {
        #     'name': 'SegWit2x',
        #     'url': '127.0.0.1',
        #     'port': 18332,
        #     'testnet': True
        # }
}


# Further set up fork matrix
for name, fork in NODES.items():
    if fork['testnet']:
        bitcoin.SelectParams('testnet')
    else:
        bitcoin.SelectParams('mainnet')
    fork['rpc'] = bitcoin.rpc.Proxy(service_url=fork['url'], service_port=fork['port'])
    print('>> rpc created {}'.format(fork['rpc']))


def create_and_send_rbf_transaction(fork, to_address, amount):
    rpc = fork['rpc']
    feeperbyte1 = FEE / 1000 * COIN
    fork['last_feeperbyte'] = feeperbyte1

    # Construct payment tx
    payment_address = CBitcoinAddress(to_address)

    payment_txout = CMutableTxOut(int(amount * COIN), payment_address.to_scriptPubKey())
    change_txout = CMutableTxOut(0, rpc.getnewaddress().to_scriptPubKey())

    tx = CMutableTransaction()
    tx.vout.append(change_txout)
    tx.vout.append(payment_txout)

    tx1_nSequence = 0xFFFFFFFF - 2

    # Add inputs until we meet the fee1 threshold
    unspent = sorted(rpc.listunspent(1), key=lambda x: x['amount'])
    value_in = 0
    value_out = sum([vout.nValue for vout in tx.vout])
    while (value_in - value_out) / len(tx.serialize()) < feeperbyte1:
        # What's the delta fee that we need to get to our desired fees per byte at
        # the current tx size?
        delta_fee = math.ceil((feeperbyte1 * len(tx.serialize())) - (value_in - value_out))

        logging.debug('Delta fee: %s' % str_money_value(delta_fee))

        # Do we need to add another input?
        if value_in - value_out < 0:
            new_outpoint = unspent[-1]['outpoint']
            new_amount = unspent[-1]['amount']
            unspent = unspent[:-1]

            logging.debug('Adding new input %s:%d with value %s BTC' % \
                          (b2lx(new_outpoint.hash), new_outpoint.n,
                           str_money_value(new_amount)))

            new_txin = CMutableTxIn(new_outpoint, nSequence=tx1_nSequence)
            tx.vin.append(new_txin)

            value_in += new_amount
            change_txout.nValue += new_amount
            value_out += new_amount

            # Resign the tx so we can figure out how large the new input's scriptSig will be.
            r = rpc.signrawtransaction(tx)
            assert (r['complete'])

            tx.vin[-1].scriptSig = r['tx'].vin[-1].scriptSig

    r = rpc.signrawtransaction(tx)
    assert (r['complete'])
    tx = r['tx']
    logging.debug('Sending tx %s' % b2x(tx.serialize()))
    txid = rpc.sendrawtransaction(tx)
    txid_hex = b2lx(txid)
    print(txid_hex)
    return txid_hex


def replace_and_resend_transaction(fork, txid, new_address):
    """
    Replace recipient
    """
    rpc = fork['rpc']
    last_feeperbyte = fork['last_feeperbyte']
    feeperbyte2 = last_feeperbyte * RATIO

    rpc.gettransaction(txid)

    txinfo = rpc.getrawtransaction(txid, True)
    tx = CMutableTransaction.from_tx(txinfo['tx'])

    # Find total value in
    value_in = 0
    for vin in tx.vin:
        prevout_tx = rpc.getrawtransaction(vin.prevout.hash)
        value_in += prevout_tx.vout[vin.prevout.n].nValue

    # Double-spend! Remove all but the change output
    tx.vout = tx.vout[0:1]
    change_txout = tx.vout[0]
    value_out = value_in
    change_txout.nValue = value_out

    # FIXME: need to modularize this code
    while (value_in - value_out) / len(tx.serialize()) < feeperbyte2:
        # What's the delta fee that we need to get to our desired fees per byte at
        # the current tx size?
        delta_fee = math.ceil((feeperbyte2 * len(tx.serialize())) - (value_in - value_out))

        logging.debug('Delta fee: %s' % str_money_value(delta_fee))

        # Do we need to add another input?
        if value_in - value_out < 0:
            new_outpoint = unspent[-1]['outpoint']
            new_amount = unspent[-1]['amount']
            unspent = unspent[:-1]

            logging.debug('Adding new input %s:%d with value %s BTC' %
                          (b2lx(new_outpoint.hash), new_outpoint.n,
                           str_money_value(new_amount)))

            tx2_nSequence = 0xFFFFFFFF - 2
            new_txin = CMutableTxIn(new_outpoint, nSequence=tx2_nSequence)
            tx.vin.append(new_txin)

            value_in += new_amount
            change_txout.nValue += new_amount
            value_out += new_amount

            # Resign the tx so we can figure out how large the new input's scriptSig will be.
            r = rpc.signrawtransaction(tx)
            assert (r['complete'])

            tx.vin[-1].scriptSig = r['tx'].vin[-1].scriptSig

    r = rpc.signrawtransaction(tx)
    assert (r['complete'])
    tx = r['tx']
    logging.debug('Sending tx %s' % b2x(tx.serialize()))
    txid = rpc.sendrawtransaction(tx)
    txid_hex = b2lx(txid)
    print(txid_hex)
    return txid_hex


def replay_transaction(txid):
    pass

create_and_send_rbf_transaction(NODES['original'], 'mgwXKtcNdpRaLwFAABaLPBswQnusob6VAX', 0.012)