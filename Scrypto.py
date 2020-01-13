#############################################
# Scrypto (distribution)
# Daniel Fritzson
# 6/12/19
#
import json
import logging
import socket, sys, traceback
import time
import urllib
import urllib2
from datetime import datetime
import os
import requests
import xlsxwriter
import smtplib

# imports public 3rd party Python wrappers for each exchange's API. Saves me a lot of effort of making my own.
#       -In future state, these wrappers would be modified to abstract each exchange's API differences
#       -This would allow for multiple functions with similar purposes to be combined and reused, allowing for easier expansion to more exchanges
from binance.client import Client
from kucoin.kucoin.client import Client_ku
from bittrex import bittrex

# xPrint() prints all status messages to the console and logs them to a text file
#       -Meant to be used in place of a standard print function
#
def xPrint(*vars):
    global logEverything
    msg=""
    for var in vars:
        if isinstance(var, str):
            msg += var
        else:
            msg += (str(var) + ' ')
    if logEverything | (msg[:3] == '!!!'):
        print msg
        errorLog.write('\n' + msg)

#
# scanMarkets gets the current market summaries for the approved pairs.
#       -Called once per iteration of main loop
#       -Results are used to look for opportunities based solely on current listed price differences
#       -Follows a get_tickers api call typically but varies by exchange. Does not actually look into orderbook prices yet
#       -Outputs a list of approved pairs and their current ticker prices to be used in compKucoinBinance and compBittrexBinance functions
#
def scanMarkets(scanBittrex, scanBinance, scanKucoin):

    xPrint('Scanning Markets...')
    bittrex_list = []
    binance_list = []
    kucoin_list = []

    if scanBittrex: 
        bittrex_markets = bittrex_api.getmarketsummaries() 
        xPrint('Got Bittrex markets.')
        for n in range(0, len(bittrex_markets)):
            MarketName = bittrex_markets[n]['MarketName']
            base = MarketName[:3]
            target = MarketName[-1*(len(MarketName)-4):]
            symbol = target + base
            if (symbol in approved_pairs): 
                if (coin_atts[target]['Enabled']):
                    bittrex_list.append(bittrex_markets[n])
    
    if scanBinance: 
        binance_orderbooks = binance_client.get_orderbook_tickers()
        xPrint('Got Binance markets.')
        for n in range(0, len(binance_orderbooks)):
            symbol = binance_orderbooks[n]['symbol']
            base = symbol[-3:]
            target = symbol[:len(symbol)-3]
            if (symbol in approved_pairs):
                if (coin_atts[target]['Enabled']):
                    binance_list.append(binance_orderbooks[n])

    if scanKucoin: 
        try:
            kucoin_markets = kucoin_client.get_ticker()['ticker'] 
            xPrint('Got Kucoin markets.')
            for n in range(0, len(kucoin_markets)):
                marketName = kucoin_markets[n]['symbol']
                # if marketName == 'XRB-BTC': marketName = 'NANO-BTC'     # NANO still listed as XRB on Kucoin but listed as NANO on Binance
                # elif marketName == 'XRB-ETH': marketName = 'NANO-ETH'
                base = marketName[-3:]
                target = marketName[:len(marketName)-4]
                symbol = target + base
                if symbol in approved_pairs:
                    if coin_atts[target]['Enabled']:
                        kucoin_list.append(kucoin_markets[n])
        except:
            tracebackStr= traceback.format_exc()
            xPrint("Unexpected error:")
            xPrint(tracebackStr)
            time.sleep(5)
            pass

    return bittrex_list, binance_list, kucoin_list

# determinePriceQuantity traverses the orderbooks for the given pair of coins on two exchanges to determine the maximum price and quantity 
# at which to place a buy/sell order
#       -Maximum price and quantity is limited by the minimum percentage profit per trade as set by the user at the start of the program
#       -Leads to an optimization problem, which would likely cost time. Simple solution is to scan one side of orderbooks (e.g. bids) 
#        then the next side (e.g. asks) and call it a day
#       -Does not require an API call since the orderbooks have been passed in as parameters from the calling function compBittrexBinance or compKucoinBinance
#
def determinePriceQuantity(bitOrderBook, binOrderBook, side, base, target, threshold):
    xPrint('Determining optimal price and quantity.')
    xPrint('Side: ' + side)
    finalPctDiff = 0
    finalBitPrice = 0
    finalBinPrice = 0
    finalQty = 0
    runningBitBase = 0
    runningBinBase = 0
    semiFinalQty = 0
    movingBitAvg = 0
    movingBinAvg = 0
    needMore = False
    if side == 'buy':
        bitKey = 'sell'                 #'sell' is equivalent to 'ask' prices
        binKey = 'bids'
        bitCurrency = base              # used at the bottom of this function to check balances
        binCurrency = target
    elif side == 'sell':
        bitKey = 'buy'                  #'buy' is equivalent to 'bid' prices
        binKey = 'asks'
        bitCurrency = target
        binCurrency = base
    if bitOrderBook[bitKey]:            # checking for an obscure error that sometimes doesn't load one side of order books correctly
        topBitPrice = float(bitOrderBook[bitKey][0]['Rate'])
        topBitQty = float(bitOrderBook[bitKey][0]['Quantity'])
        movingBitAvg = topBitPrice
        runningBitBase = topBitPrice*topBitQty
    else:
        topBitPrice = 0
        topBitQty = 0
        xPrint('Coin likely under maintenance on Bittrex.')
    if binOrderBook[binKey]:             # checking for an obscure error that sometimes doesn't load one side of order books correctly
        topBinPrice = float(binOrderBook[binKey][0][0])
        topBinQty = float(binOrderBook[binKey][0][1])
        movingBinAvg = topBinPrice
        runningBinBase = topBinPrice*topBinQty
    else:
        topBinPrice = 0
        topBinQty = 0
        xPrint('Coin likely under maintenance on Binance.')
    if (topBitPrice != 0) & (topBinPrice != 0):
        if side == 'buy': finalPctDiff = (topBinPrice - topBitPrice)/topBinPrice
        if side == 'sell': finalPctDiff = (topBitPrice - topBinPrice)/topBitPrice
        xPrint('ORIGINAL PCTDIFF = ', round(finalPctDiff*100, 4), '%')
        if finalPctDiff < significance:
            topBitPrice = 0
            topBinPrice = 0
            xPrint('OPPORTUNITY DISAPPEARED')
        startVal = 1

        #Checks the case where both sites have a lower base than the threshold
    if (topBitPrice != 0) & (topBinPrice != 0):
        while (topBitQty*topBitPrice < threshold) & (topBinQty*topBinPrice < threshold) & (startVal < 5):
            nextBitPrice = float(bitOrderBook[bitKey][startVal]['Rate'])
            nextBitQty = float(bitOrderBook[bitKey][startVal]['Quantity'])
            nextBinPrice = float(binOrderBook[binKey][startVal][0])
            nextBinQty = float(binOrderBook[binKey][startVal][1])
            if side == 'buy':
                pctDiff = (nextBinPrice - nextBitPrice)/nextBinPrice
            elif side == 'sell':
                pctDiff = (nextBitPrice - nextBinPrice)/nextBitPrice
            if pctDiff > significance:
                topBitPrice = nextBitPrice
                topBitQty += nextBitQty
                topBinPrice = nextBinPrice
                topBinQty += nextBinQty
            else:
                topBitPrice = 0
                topBitQty = 0
                topBinPrice = 0
                topBinQty = 0
                movingBitAvg = 0
                movingBinAvg = 0
                xPrint('OPPORTUNITY DID NOT MEET THRESHOLD')
                break
            startVal += 1
        totalBitQty = topBitQty
        totalBinQty = topBinQty
        finalBitPrice = topBitPrice
        finalBinPrice = topBinPrice
        lowQty = 0
        finalQty = 0
        pctDiff = 0
        runningBitBase = totalBitQty*finalBitPrice
        runningBinBase = totalBinQty*finalBinPrice
        if totalBitQty > 0: movingBitAvg = runningBitBase/totalBitQty
        if totalBinQty > 0: movingBinAvg = runningBinBase/totalBinQty

        #Increases qty of lower qty side until it reaches a price that no longer meets significance
        n = startVal
        xPrint('START BITTREX QTY: ', totalBitQty)
        xPrint('START BINANCE QTY: ', totalBinQty)
        if totalBitQty > totalBinQty:
            while (totalBitQty > totalBinQty) & (n < 10):
                if n == startVal: xPrint('Bittrex Qty > Binance Qty. Scanning down Binance List...')
                xPrint('N = ', n)
                binPrice = float(binOrderBook[binKey][n][0])
                binQty = float(binOrderBook[binKey][n][1])
                if binKey == 'bids':
                    pctDiff = (binPrice - topBitPrice)/binPrice
                elif binKey == 'asks':
                    pctDiff = (topBitPrice - binPrice)/topBitPrice
                if (pctDiff > significance):
                    totalBinQty += binQty
                    finalBinPrice = binPrice
                    finalPctDiff = pctDiff
                    runningBinBase += binPrice*binQty
                    # xPrint('RUNNING BASE: ', runningBinBase))
                    # xPrint('pctDiff: ' + str(pctDiff))
                else: break
                if n > 9: break
                n += 1
            n = startVal
            movingBinAvg = runningBinBase/totalBinQty
            while (totalBinQty > totalBitQty) & (n < 10):
                if n == startVal: xPrint('Binance Qty > Bittrex Qty. Scanning down Bittrex List...')
                xPrint('N = ', n)
                bitPrice = float(bitOrderBook[bitKey][n]['Rate'])
                bitQty = float(bitOrderBook[bitKey][n]['Quantity'])
                if bitKey == 'buy':
                    pctDiff = (bitPrice - topBinPrice)/bitPrice
                elif bitKey == 'sell':
                    pctDiff = (topBinPrice - bitPrice)/topBinPrice
                if (pctDiff > significance): 
                    totalBitQty += bitQty
                    finalBitPrice = bitPrice
                    finalPctDiff = pctDiff
                    runningBitBase += bitPrice*bitQty
                    # xPrint('RUNNING BASE: ', runningBitBase))
                    # xPrint('pctDiff: ', pctDiff))
                else: break
                if n > 9: break
                n += 1
            n = startVal
            movingBitAvg = runningBitBase/totalBitQty
        elif totalBinQty > totalBitQty:
            while (totalBinQty > totalBitQty) & (n < 10):
                if n == startVal: xPrint('Binance Qty > Bittrex Qty. Scanning down Bittrex List...')
                xPrint('N = ', n)
                bitPrice = float(bitOrderBook[bitKey][n]['Rate'])
                bitQty = float(bitOrderBook[bitKey][n]['Quantity'])
                if bitKey == 'buy':
                    pctDiff = (bitPrice - topBinPrice)/bitPrice
                elif bitKey == 'sell':
                    pctDiff = (topBinPrice - bitPrice)/topBinPrice
                if (pctDiff > significance): 
                    totalBitQty += bitQty
                    finalBitPrice = bitPrice
                    finalPctDiff = pctDiff
                    runningBitBase += bitPrice*bitQty
                    # xPrint('RUNNING BASE: ' + str(runningBitBase))
                    # xPrint('pctDiff: ' + str(pctDiff))
                else: break
                n += 1
            n = startVal
            movingBitAvg = runningBitBase/totalBitQty
            while (totalBitQty > totalBinQty) & (n < 10):
                if n == startVal: xPrint('Bittrex Qty > Binance Qty. Scanning down Binance List...')
                xPrint('N = ', n)
                binPrice = float(binOrderBook[binKey][n][0])
                binQty = float(binOrderBook[binKey][n][1])
                if binKey == 'bids':
                    pctDiff = (binPrice - topBitPrice)/binPrice
                elif binKey == 'asks':
                    pctDiff = (topBitPrice - binPrice)/topBitPrice
                if (pctDiff > significance):
                    totalBinQty += binQty
                    finalBinPrice = binPrice
                    finalPctDiff = pctDiff
                    runningBinBase += binPrice*binQty
                    # xPrint('RUNNING BASE: ' + str(runningBinBase))
                    # xPrint('pctDiff: ' + str(pctDiff))
                else: break
                n += 1
            movingBinAvg = runningBinBase/totalBinQty
        if totalBitQty < totalBinQty: finalQty = totalBitQty
        else: finalQty = totalBinQty    
        semiFinalQty = finalQty

    if (finalBinPrice != 0) & (finalBitPrice != 0):
        ownAsset = False
        for n in range(0, len(bittrex_balances)):
            if bittrex_balances[n]['Currency'] == bitCurrency: ownAsset = True
            if (side == 'buy') & (bittrex_balances[n]['Currency'] == bitCurrency) & (float(bittrex_balances[n]['Available'])/finalBitPrice < finalQty):
                finalQty = float(bittrex_balances[n]['Available'])*0.97
                if finalQty < threshold:
                    xPrint('Missed opportunity. Do not own enough of this base currency on this exchange.')
                    coin_atts[bitCurrency]['missedOpps'] += 1
                    needMore = True
            if (side == 'sell') & (bittrex_balances[n]['Currency'] == bitCurrency) & (float(bittrex_balances[n]['Available']) < finalQty):
                finalQty = float(bittrex_balances[n]['Available'])*0.97
                if float(finalQty)*float(finalBitPrice) < threshold:
                    xPrint('Missed opportunity. Do not own enough of this coin on this exchange.')
                    coin_atts[bitCurrency]['missedOpps'] += 1
                    needMore = True
        for n in range(0, len(binance_balances)):
            if (side == 'sell') & (binance_balances[n]['asset'] == binCurrency) & (float(binance_balances[n]['free'])/finalBinPrice < finalQty):
                finalQty = float(binance_balances[n]['free'])*0.97
                if finalQty < threshold:
                    xPrint('Missed opportunity. Do not own enough of this base currency on this exchange.')
                    coin_atts[binCurrency]['missedOpps'] += 1
                    needMore = True
            if (side == 'buy') & (binance_balances[n]['asset'] == binCurrency) & (float(binance_balances[n]['free']) < finalQty):
                finalQty = float(binance_balances[n]['free'])*0.97
                if float(finalQty)*float(finalBinPrice) < threshold:
                    xPrint('Missed opportunity. Do not own enough of this coin on this exchange.')
                    coin_atts[binCurrency]['missedOpps'] += 1
                    needMore = True
        if ownAsset == False: 
            xPrint("You do not own this coin.")
            finalQty = 0              #only need to check Bittrex since Binance returns zero balances
    
    # ETH requires 0.1 to be in a bittrex account in order to deposit to it
    if ((base == 'ETH') & (side == 'buy')) | ((target == 'ETH') & (side == 'sell')):
        finalQty -= 0.11
    if finalQty < 0: finalQty = 0
    if movingBitAvg > movingBinAvg: finalPctDiff = (movingBitAvg - movingBinAvg)/movingBitAvg
    elif movingBinAvg > movingBitAvg: finalPctDiff = (movingBinAvg - movingBitAvg)/movingBinAvg
    elif movingBitAvg == movingBinAvg: finalPctDiff = 0
    grossBitSum = movingBitAvg*semiFinalQty
    grossBinSum = movingBinAvg*semiFinalQty
    xPrint('FINAL AVG PCTDIFF: ', round(finalPctDiff*100, 4), '%')

    return float(finalQty), float(finalBitPrice), float(finalBinPrice), finalPctDiff, float(grossBitSum), float(grossBinSum), needMore

def determinePriceQuantityKu(kuOrderBook, binOrderBook, side, base, target, threshold):
    xPrint('Determining optimal price and quantity.')
    xPrint('Side: ' + side)
    finalPctDiff = 0
    finalKuPrice = 0
    finalBinPrice = 0
    finalQty = 0
    runningKuBase = 0
    runningBinBase = 0
    semiFinalQty = 0
    movingKuAvg = 0
    movingBinAvg = 0
    needMore = False
    if side == 'buy':
        kuKey = 'bids'                 #'sell' is equivalent to 'ask' prices
        binKey = 'bids'
        kuCurrency = base              # used at the bottom of this function to check balances
        binCurrency = target
    elif side == 'sell':
        kuKey = 'asks'                  #'buy' is equivalent to 'bid' prices
        binKey = 'asks'
        kuCurrency = target
        binCurrency = base
    if kuOrderBook[kuKey]:            # checking for a weird error that sometimes doesn't load one side of order books correctly
        topKuPrice = float(kuOrderBook[kuKey][0][0])
        topKuQty = float(kuOrderBook[kuKey][0][1])
        movingKuAvg = topKuPrice
        runningKuBase = topKuPrice*topKuQty
    else:
        topKuPrice = 0
        topKuQty = 0
        xPrint('Coin likely under maintenance on Kucoin.')
    if binOrderBook[binKey]:             # checking for a weird error that sometimes doesn't load one side of order books correctly
        topBinPrice = float(binOrderBook[binKey][0][0])
        topBinQty = float(binOrderBook[binKey][0][1])
        movingBinAvg = topBinPrice
        runningBinBase = topBinPrice*topBinQty
    else:
        topBinPrice = 0
        topBinQty = 0
        xPrint('Coin likely under maintenance on Binance.')
    if (topKuPrice != 0) & (topBinPrice != 0):
        if side == 'buy': finalPctDiff = (topBinPrice - topKuPrice)/topBinPrice
        if side == 'sell': finalPctDiff = (topKuPrice - topBinPrice)/topKuPrice
        xPrint('ORIGINAL PCTDIFF = ', round(finalPctDiff*100, 4), '%')
        if finalPctDiff < significance:
            topKuPrice = 0
            topBinPrice = 0
            xPrint('OPPORTUNITY DISAPPEARED')
        startVal = 1

        # Checks the case where both sites have a lower base than the threshold
    if (topKuPrice != 0) & (topBinPrice != 0):
        while (topKuQty*topKuPrice < threshold) & (topBinQty*topBinPrice < threshold) & (startVal < 5):
            nextKuPrice = float(kuOrderBook[kuKey][startVal][0])
            nextKuQty = float(kuOrderBook[kuKey][startVal][1])
            nextBinPrice = float(binOrderBook[binKey][startVal][0])
            nextBinQty = float(binOrderBook[binKey][startVal][1])
            if side == 'buy':
                pctDiff = (nextBinPrice - nextKuPrice)/nextBinPrice
            elif side == 'sell':
                pctDiff = (nextKuPrice - nextBinPrice)/nextKuPrice
            if pctDiff > significanceKu:
                topKuPrice = nextKuPrice
                topKuQty += nextKuQty
                topKuPrice = nextKuPrice
                topKuQty += nextKuQty
            else:
                topKuPrice = 0
                topKuQty = 0
                topBinPrice = 0
                topBinQty = 0
                movingKuAvg = 0
                movingBinAvg = 0
                xPrint('OPPORTUNITY DID NOT MEET THRESHOLD')
                break
            startVal += 1
        totalKuQty = topKuQty
        totalBinQty = topBinQty
        finalKuPrice = topKuPrice
        finalBinPrice = topBinPrice
        lowQty = 0
        finalQty = 0
        pctDiff = 0
        runningKuBase = totalKuQty*finalKuPrice
        runningBinBase = totalBinQty*finalBinPrice
        if totalKuQty > 0: movingKuAvg = runningKuBase/totalKuQty
        if totalBinQty > 0: movingBinAvg = runningBinBase/totalBinQty

        #Increases qty of lower qty side until it reaches a price that no longer meets significanceKu
        n = startVal
        xPrint('START KUCOIN QTY: ', totalKuQty)
        xPrint('START BINANCE QTY: ', totalBinQty)
        if totalKuQty > totalBinQty:
            while (totalKuQty > totalBinQty) & (n < 10):
                if n == startVal: xPrint('Kucoin Qty > Binance Qty. Scanning down Binance List...')
                xPrint('N = ', n)
                binPrice = float(binOrderBook[binKey][n][0])
                binQty = float(binOrderBook[binKey][n][1])
                if binKey == 'bids':
                    pctDiff = (binPrice - topKuPrice)/binPrice
                elif binKey == 'asks':
                    pctDiff = (topKuPrice - binPrice)/topKuPrice
                if (pctDiff > significanceKu):
                    totalBinQty += binQty
                    finalBinPrice = binPrice
                    finalPctDiff = pctDiff
                    runningBinBase += binPrice*binQty
                    # xPrint('RUNNING BASE: ', runningBinBase))
                    # xPrint('pctDiff: ' + str(pctDiff))
                else: break
                if n > 9: break
                n += 1
            n = startVal
            movingBinAvg = runningBinBase/totalBinQty
            while (totalBinQty > totalKuQty) & (n < 10):
                if n == startVal: xPrint('Binance Qty > Kucoin Qty. Scanning down Kucoin List...')
                xPrint('N = ', n)
                kuPrice = float(kuOrderBook[kuKey][n][0])
                kuQty = float(kuOrderBook[kuKey][n][1])
                if kuKey == 'asks':
                    pctDiff = (kuPrice - topBinPrice)/kuPrice
                elif kuKey == 'bids':
                    pctDiff = (topBinPrice - kuPrice)/topBinPrice
                if (pctDiff > significanceKu): 
                    totalKuQty += kuQty
                    finalKuPrice = kuPrice
                    finalPctDiff = pctDiff
                    runningKuBase += kuPrice*kuQty
                    # xPrint('RUNNING BASE: ', runningKuBase))
                    # xPrint('pctDiff: ', pctDiff))
                else: break
                if n > 9: break
                n += 1
            n = startVal
            movingKuAvg = runningKuBase/totalKuQty
        elif totalBinQty > totalKuQty:
            while (totalBinQty > totalKuQty) & (n < 10):
                if n == startVal: xPrint('Binance Qty > Kucoin Qty. Scanning down Kucoin List...')
                xPrint('N = ', n)
                kuPrice = float(kuOrderBook[kuKey][n][0])
                kuQty = float(kuOrderBook[kuKey][n][1])
                if kuKey == 'asks':
                    pctDiff = (kuPrice - topBinPrice)/kuPrice
                elif kuKey == 'bids':
                    pctDiff = (topBinPrice - kuPrice)/topBinPrice
                if (pctDiff > significanceKu): 
                    totalKuQty += kuQty
                    finalKuPrice = kuPrice
                    finalPctDiff = pctDiff
                    runningKuBase += kuPrice*kuQty
                    # xPrint('RUNNING BASE: ' + str(runningKuBase))
                    # xPrint('pctDiff: ' + str(pctDiff))
                else: break
                n += 1
            n = startVal
            movingKuAvg = runningKuBase/totalKuQty
            while (totalKuQty > totalBinQty) & (n < 10):
                if n == startVal: xPrint('Kucoin Qty > Binance Qty. Scanning down Binance List...')
                xPrint('N = ', n)
                binPrice = float(binOrderBook[binKey][n][0])
                binQty = float(binOrderBook[binKey][n][1])
                if binKey == 'bids':
                    pctDiff = (binPrice - topKuPrice)/binPrice
                elif binKey == 'asks':
                    pctDiff = (topKuPrice - binPrice)/topKuPrice
                if (pctDiff > significanceKu):
                    totalBinQty += binQty
                    finalBinPrice = binPrice
                    finalPctDiff = pctDiff
                    runningBinBase += binPrice*binQty
                    # xPrint('RUNNING BASE: ' + str(runningBinBase))
                    # xPrint('pctDiff: ' + str(pctDiff))
                else: break
                n += 1
            movingBinAvg = runningBinBase/totalBinQty
        if totalKuQty < totalBinQty: finalQty = totalKuQty
        else: finalQty = totalBinQty    
        semiFinalQty = finalQty

    if (finalBinPrice != 0) & (finalKuPrice != 0):
        ownAsset = False
        attKuCurrency = kuCurrency
        # if kuCurrency == 'NANO': kuCurrency = 'XRB'         # Balances will report Kucoin NANO as XRB
        for n in range(0, len(kucoin_balances)):
            if kucoin_balances[n]['currency'] == kuCurrency: ownAsset = True
            if (side == 'buy') & (kucoin_balances[n]['currency'] == kuCurrency) & (float(kucoin_balances[n]['balance'])/finalKuPrice < finalQty):
                finalQty = float(kucoin_balances[n]['balance'])*0.97
                if finalQty < threshold:
                    xPrint('Missed opportunity. Do not own enough of this base currency on this exchange.')

                    coin_atts[attKuCurrency]['missedOpps'] += 1
                    needMore = True
            if (side == 'sell') & (kucoin_balances[n]['currency'] == kuCurrency) & (float(kucoin_balances[n]['balance']) < finalQty):
                finalQty = float(kucoin_balances[n]['balance'])*0.97
                if float(finalQty)*float(finalKuPrice) < threshold:
                    xPrint('Missed opportunity. Do not own enough of this coin on Kucoin.')
                    coin_atts[attKuCurrency]['missedOpps'] += 1
                    needMore = True
        for n in range(0, len(binance_balances)):
            if (side == 'sell') & (binance_balances[n]['asset'] == binCurrency) & (float(binance_balances[n]['free'])/finalBinPrice < finalQty):
                finalQty = float(binance_balances[n]['free'])*0.97
                if finalQty < threshold:
                    xPrint('Missed opportunity. Do not own enough of this base currency on this exchange.')
                    coin_atts[binCurrency]['missedOpps'] += 1
                    needMore = True
            if (side == 'buy') & (binance_balances[n]['asset'] == binCurrency) & (float(binance_balances[n]['free']) < finalQty):
                finalQty = float(binance_balances[n]['free'])*0.97
                if float(finalQty)*float(finalBinPrice) < threshold:
                    xPrint('Missed opportunity. Do not own enough of this coin on this exchange.')
                    coin_atts[binCurrency]['missedOpps'] += 1
                    needMore = True
        if ownAsset == False: 
            xPrint("You do not own this coin.")
            finalQty = 0              #only need to check Kucoin since Binance returns zero balances
    
    # ETH requires 0.1 to be in a Kucoin account in order to deposit to it
    if ((base == 'ETH') & (side == 'buy')) | ((target == 'ETH') & (side == 'sell')):
        finalQty -= 0.11
    if finalQty < 0: finalQty = 0
    if movingKuAvg > movingBinAvg: finalPctDiff = (movingKuAvg - movingBinAvg)/movingKuAvg
    elif movingBinAvg > movingKuAvg: finalPctDiff = (movingBinAvg - movingKuAvg)/movingBinAvg
    elif movingKuAvg == movingBinAvg: finalPctDiff = 0
    grossKuSum = movingKuAvg*semiFinalQty
    grossBinSum = movingBinAvg*semiFinalQty
    xPrint('FINAL AVG PCTDIFF: ', round(finalPctDiff*100, 4), '%')

    return float(finalQty), float(finalKuPrice), float(finalBinPrice), finalPctDiff, float(grossKuSum), float(grossBinSum), needMore

def compKucoinBinance(kucoin_list, binance_list):
    global kucoin_balances
    global binance_balances
    global coin_atts
    global significanceKu

    for n in range(0, len(kucoin_list)):
        ask_ku = float(kucoin_list[n]['sell'])
        bid_ku = float(kucoin_list[n]['buy'])
        marketName = kucoin_list[n]['symbol']
        # if marketName == 'XRB-BTC': marketName = 'NANO-BTC'
        # elif marketName == 'XRB-ETH': marketName = 'NANO-ETH'
        if len(marketName) > 3:
            base = marketName[-3:]
            target = marketName[:(len(marketName)-4)]
        else:
            continue
        symbol = target + base 
        threshold = 10000
        if base == 'BTC': threshold = 0.0305        #arbitrary limits that would make a trade even worth the trouble
        elif base == 'ETH': threshold = 0.35
        if (symbol in approved_pairs) & (target in approved_kucoins):
            if (coin_atts[target]['Enabled']):
                # xPrint('Checking opportunities for ', symbol)
                for i in range(0, len(binance_list)):
                    if binance_list[i]['symbol'] == symbol:
                        ask_bin = float(binance_list[i]['askPrice'])
                        askQty_bin = float(binance_list[i]['askQty'])
                        bid_bin = float(binance_list[i]['bidPrice'])
                        bidQty_bin = float(binance_list[i]['bidQty'])
                        pctDiff = 0
                        bid1 = False
                        bid2 = False
                        side = ''
                        if (bid_bin > ask_ku):
                            difference = bid_bin - ask_ku
                            pctDiff = difference/bid_bin
                            bid1 = True
                            side = 'buy'                #'buy' means buy on Kucoin
                        elif (bid_ku > ask_bin):
                            difference = bid_ku - ask_bin
                            pctDiff = difference/bid_ku
                            bid2 = True
                            side = 'sell'               #'sell' means sell on Kucoin
                        if pctDiff > significanceKu:
                            xPrint('Found possible opportunity.')
                            try:
                                # if marketName == 'NANO-BTC': marketName = 'XRB-BTC' # Have to switch it back to get the order books
                                # elif marketName == 'NANO-ETH': marketName = 'XRB-ETH'
                                kuOrderBook = kucoin_client.get_order_book(symbol=marketName)
                                binOrderBook = binance_client.get_order_book(symbol=symbol, limit=20)
                            except KeyboardInterrupt:
                                tracebackStr= traceback.format_exc()
                                xPrint('PAUSED')
                                changeSig = raw_input('Would you like to change the Bittrex/Binance significance (y/n): ')
                                if changeSig == 'y':
                                    significance = input('Enter new significance: ')
                                changeSig = raw_input('Would you like to change the Kucoin/Binance significance (y/n): ')
                                if changeSig == 'y':
                                    significanceKu = input('Enter new significance: ')
                                resume = raw_input('Hit enter to continue.')
                                writeBalancesLog(3)
                                continue
                            except urllib2.HTTPError:
                                tracebackStr= traceback.format_exc()
                                xPrint('URLLIB ERROR ')
                                xPrint(tracebackStr)
                                time.sleep(5)
                                continue
                            except urllib2.URLError:
                                tracebackStr= traceback.format_exc()
                                xPrint('URLLIB ERROR ')
                                xPrint(tracebackStr)
                                time.sleep(5)
                                continue
                            except requests.exceptions.RequestException:
                                tracebackStr= traceback.format_exc()
                                xPrint('REQUESTS ERROR ')
                                xPrint(tracebackStr)
                                time.sleep(5)
                                continue
                            except:
                                tracebackStr= traceback.format_exc()
                                xPrint("Unexpected error:")
                                xPrint(tracebackStr)
                                continue
                            xPrint('Retrieved order books.')
                            try:
                                topBidBin = float(binOrderBook['bids'][0][0])
                                topAskBin = float(binOrderBook['asks'][0][0])
                                topBidKu = float(kuOrderBook['bids'][0][0])
                                topAskKu = float(kuOrderBook['asks'][0][0])
                            except:
                                topBidBin = bid_bin
                                topAskBin = ask_bin
                                topBidKu = bid_ku
                                topAskKu = ask_ku
                                continue
                            askKuDiff = topAskKu - ask_ku
                            askBinDiff = topAskBin - ask_bin
                            bidKuDiff = topBidKu - bid_ku
                            bidBinDiff = topBidBin - bid_bin
                            # if target == 'XRB': target = 'NANO'
                            quantity, kuPrice, binPrice, pctDiff, grossKuSum, grossBinSum, needMore = determinePriceQuantityKu(kuOrderBook, binOrderBook, side, base, target, threshold)
                            precision = int(coin_atts[target]['Precision'])
                            quantity = round(0.99999*quantity, precision)
                            if base == 'ETH':
                                kuPrice = '{:.6f}'.format(kuPrice)
                                binPrice = '{:.6f}'.format(binPrice)
                            else:
                                kuPrice = '{:.8f}'.format(kuPrice)
                                binPrice = '{:.8f}'.format(binPrice)
                            xPrint('SYMBOL: ', symbol)
                            xPrint('Kucoin: ' + str(kuPrice))
                            xPrint('Binance: ' + str(binPrice))
                            xPrint('Quantity: ' + str(quantity))
                            xPrint('Threshold: ' + str(threshold))
                            xPrint('Base: ', float(kuPrice)*quantity)

                            # If there is not enough capital to even attempt the trade, we should withdraw from the other side to get more. The actual withdraw
                            # functions will take care of checking what coins to withdraw and whether or not there is enough to withdraw from the other side
                            if (needMore == True):
                                xPrint('Getting more of this asset from the other exchange...')
                                if (binPrice > kuPrice): withdrawBuyKucoin(base, target, threshold, kuPrice, binPrice)
                                elif (kuPrice > binPrice): withdrawSellKucoin(base, target, threshold, kuPrice, binPrice)
                                else: xPrint('Prices are equal. No opportunity.')
                                continue
                            
                            # If there is enough capital, we should attempt the trade
                            if ((binPrice > kuPrice) & (float(kuPrice)*quantity > threshold) & (float(binPrice)*quantity > threshold)):
                                xPrint('OPPORTUNITY FOUND')
                                xPrint(symbol + ': ' + str(pctDiff*100) + '%')
                                xPrint('Buy at Kucoin: ' + str(kuPrice))
                                xPrint('Total Base: ' + str(float(kuPrice)*quantity))
                                xPrint('Sell at Binance: ' + str(binPrice))
                                xPrint('Total Base: ' + str(float(binPrice)*quantity))
                                
                                netProfit = 0
                                netBuyCost = 0
                                netSellCost = 0
                                openOrder = True

                                if tradeEnabled == True:
                                    trend = 'down'                      # outdated functionality but may be of use later
                                    xPrint('Difference in ask prices on Kucoin: ', askKuDiff)
                                    xPrint('Difference in bid prices on Binance: ', bidBinDiff)
                                    quantity, netSellCost = sellBinance(symbol, quantity, binPrice, trend)
                                    xPrint('Quantity sold: ', quantity)
                                    currentSlop = float(coin_atts[target]['slop'])
                                    if currentSlop < 0.005*quantity:
                                        currentSlop = 0                 # Round out negligent slop. Arbitrarily set to 5% of the quantity of this trade. Shouldn't be too low so as to avoid unnecessary trading fees
                                    quantity = round(1.001*quantity, precision)
                                    quantitySold = quantity
                                    if (quantity*float(kuPrice) > 0.0011) | (currentSlop < 0):      # If too much has been sold in an earlier sloppy trade, buy the slop
                                        buyQuantity = quantity - currentSlop                   # Works if it's positive or negative slop
                                        uuid, quantity, netBuyCost = buyKucoin(marketName, quantity, round(1.025*float(kuPrice), 6), trend)
                                    quantityBought = quantity
                                    slop = quantityBought - quantitySold        # Should never be above 0. Always going to sell more than buy if there's a sloppy trade
                                    coin_atts[target]['slop'] += slop
                                    xPrint('Quantity bought: ', quantity)
                                        

                                netProfit = netSellCost - netBuyCost 
                                xPrint('Cost to buy: ', netBuyCost)
                                xPrint('Gain from sell: ', netSellCost)
                                xPrint('NET PROFIT: ', netProfit, base) 
                                time.sleep(2)         
                                try:
                                    kucoin_balances = kucoin_client.get_accounts()
                                    binance_balances = binance_client.get_account()['balances']
                                except KeyboardInterrupt:
                                    tracebackStr= traceback.format_exc()
                                    xPrint('PAUSED')
                                    changeSig = raw_input('Would you like to change the Bittrex/Binance significance (y/n): ')
                                    if changeSig == 'y':
                                        significance = input('Enter new significance: ')
                                    changeSig = raw_input('Would you like to change the Kucoin/Binance significance (y/n): ')
                                    if changeSig == 'y':
                                        significanceKu = input('Enter new significance: ')
                                    resume = raw_input('Hit enter to continue.')
                                    writeBalancesLog(3)
                                    continue
                                except urllib2.HTTPError:
                                    tracebackStr= traceback.format_exc()
                                    xPrint('URLLIB ERROR ')
                                    xPrint(tracebackStr)
                                    time.sleep(5)
                                    continue
                                except urllib2.URLError:
                                    tracebackStr= traceback.format_exc()
                                    xPrint('URLLIB ERROR ')
                                    xPrint(tracebackStr)
                                    time.sleep(5)
                                    continue
                                except requests.exceptions.RequestException:
                                    tracebackStr= traceback.format_exc()
                                    xPrint('REQUESTS ERROR ')
                                    xPrint(tracebackStr)
                                    time.sleep(5)
                                    continue
                                except:
                                    tracebackStr= traceback.format_exc()
                                    xPrint("Unexpected error:")
                                    xPrint(tracebackStr)
                                    resume = raw_input('Hit enter to continue.')
                                    pass
                                baseKuBalance, baseBinBalance, targetKuBalance, targetBinBalance = withdrawBuyKucoin(base, target, threshold, kuPrice, binPrice)
                                writeToLog(symbol, pctDiff, 'Kucoin', float(kuPrice), grossKuSum, 'Binance', float(binPrice), grossBinSum, float(quantity), baseKuBalance, targetKuBalance, baseBinBalance, targetBinBalance, netProfit)
                                time.sleep(2)
                            if ((kuPrice > binPrice) & (float(binPrice)*quantity > threshold) & (float(kuPrice)*quantity > threshold)):
                                xPrint('OPPORTUNITY FOUND')
                                xPrint(symbol + ': ' + str(pctDiff*100) + '%')
                                xPrint('Buy at Binance: ' + str(binPrice))
                                xPrint('Total Base: ' + str(float(binPrice)*quantity))
                                xPrint('Sell at Kucoin: ' + str(kuPrice))
                                xPrint('Total Base: ' + str(float(kuPrice)*quantity))
                                
                                netBuyCost = 0
                                netSellCost = 0
                                netProfit = 0

                                if tradeEnabled == True:
                                    trend = 'down'
                                    xPrint('Difference in ask prices on Binance: ', askBinDiff)
                                    xPrint('Difference in bid prices on Kucoin: ', bidKuDiff)
                                    currentSlop = float(coin_atts[target]['slop'])
                                    if currentSlop < 0.005*quantity:
                                        currentSlop = 0                 # Round out negligent slop. Arbitrarily set to 5% of the quantity of this trade. Shouldn't be too low so as to avoid unnecessary trading fees
                                    quantity, netBuyCost = buyBinance(symbol, quantity, binPrice, trend)
                                    quantity = round(0.999*quantity, precision)
                                    xPrint('Quantity bought: ', quantity)
                                    quantityBought = quantity
                                    if (quantity*float(kuPrice) > 0.0011) | (currentSlop > 0):          # If too much has been bought in an earlier sloppy trade, sell the slop
                                        sellQuantity = quantity + currentSlop           # Works if it's positive or negative slop
                                        quantity, netSellCost = sellKucoin(marketName, sellQuantity, round(0.975*float(kuPrice), 6), trend)
                                    quantitySold = quantity
                                    slop = quantityBought - quantitySold        # Should never be below 0. Will always sell more than buy here if there's a sloppy trade
                                    coin_atts[target]['slop'] += slop                                   

                                netProfit = netSellCost - netBuyCost
                                xPrint('Cost to buy: ', netBuyCost)
                                xPrint('Gain from sell: ', netSellCost)
                                xPrint('NET PROFIT: ', netProfit, base)   
                                time.sleep(2)
                                try:       
                                    kucoin_balances = kucoin_client.get_accounts()
                                    binance_balances = binance_client.get_account()['balances']
                                except KeyboardInterrupt:
                                    tracebackStr= traceback.format_exc()
                                    xPrint('PAUSED')
                                    changeSig = raw_input('Would you like to change the Bittrex/Binance significance (y/n): ')
                                    if changeSig == 'y':
                                        significance = input('Enter new significance: ')
                                    changeSig = raw_input('Would you like to change the Kucoin/Binance significance (y/n): ')
                                    if changeSig == 'y':
                                        significanceKu = input('Enter new significance: ')
                                    resume = raw_input('Hit enter to continue.')
                                    writeBalancesLog(3)
                                    continue
                                except urllib2.HTTPError:
                                    tracebackStr= traceback.format_exc()
                                    xPrint('URLLIB ERROR ')
                                    xPrint(tracebackStr)
                                    time.sleep(5)
                                    continue
                                except urllib2.URLError:
                                    tracebackStr= traceback.format_exc()
                                    xPrint('URLLIB ERROR ')
                                    xPrint(tracebackStr)
                                    time.sleep(5)
                                    continue
                                except requests.exceptions.RequestException:
                                    tracebackStr= traceback.format_exc()
                                    xPrint('REQUESTS ERROR ')
                                    xPrint(tracebackStr)
                                    time.sleep(5)
                                    continue
                                except:
                                    tracebackStr= traceback.format_exc()
                                    xPrint("Unexpected error:")
                                    xPrint(tracebackStr)
                                    resume = raw_input('Hit enter to continue.')
                                    pass
                                
                                baseKuBalance, baseBinBalance, targetKuBalance, targetBinBalance = withdrawSellKucoin(base, target, threshold, kuPrice, binPrice)
                                
                                writeToLog(symbol, pctDiff, 'Binance', float(binPrice), grossBinSum, 'Kucoin', float(kuPrice), grossKuSum, quantity, baseKuBalance, targetKuBalance, baseBinBalance, targetBinBalance, netProfit)
                                time.sleep(2) 

def compBittrexBinance(bittrex_list, binance_list):
    global bittrex_balances
    global binance_balances
    global coin_atts
    global significance

    for n in range(0, len(bittrex_list)):
        ask_bit = float(bittrex_list[n]['Ask'])
        bid_bit = float(bittrex_list[n]['Bid'])
        MarketName = bittrex_list[n]['MarketName']
        if len(MarketName) > 3:
            base = MarketName[:3]
            target = MarketName[-1*(len(MarketName)-4):]
        else:
            break
        symbol = target + base 
        threshold = 10000
        if base == 'BTC': threshold = 0.0305
        elif base == 'ETH': threshold = 0.35
        if (symbol in approved_pairs) & (target in approved_coins):
            if (coin_atts[target]['Enabled']):
                for i in range(0, len(binance_list)):
                    if binance_list[i]['symbol'] == symbol:
                        ask_bin = float(binance_list[i]['askPrice'])
                        askQty_bin = float(binance_list[i]['askQty'])
                        bid_bin = float(binance_list[i]['bidPrice'])
                        bidQty_bin = float(binance_list[i]['bidQty'])
                        pctDiff = 0
                        bid1 = False
                        bid2 = False
                        side = ''
                        if (bid_bin > ask_bit):
                            difference = bid_bin - ask_bit
                            pctDiff = difference/bid_bin
                            bid1 = True
                            side = 'buy'                #'buy' means buy on Bittrex
                        elif (bid_bit > ask_bin):
                            difference = bid_bit - ask_bin
                            pctDiff = difference/bid_bit
                            bid2 = True
                            side = 'sell'               #'sell' means sell on Bittrex
                        if pctDiff > significance:
                            xPrint('Found possible opportunity.')
                            try:
                                bitOrderBook = bittrex_api.getorderbook(market=MarketName, type='both', depth=20)
                                binOrderBook = binance_client.get_order_book(symbol=symbol, limit=20)
                            except KeyboardInterrupt:
                                tracebackStr= traceback.format_exc()
                                xPrint('PAUSED')
                                changeSig = raw_input('Would you like to change the Bittrex/Binance significance (y/n): ')
                                if changeSig == 'y':
                                    significance = input('Enter new significance: ')
                                changeSig = raw_input('Would you like to change the Kucoin/Binance significance (y/n): ')
                                if changeSig == 'y':
                                    significanceKu = input('Enter new significance: ')
                                resume = raw_input('Hit enter to continue.')
                                writeBalancesLog(3)
                                continue
                            except urllib2.HTTPError:
                                tracebackStr= traceback.format_exc()
                                xPrint('URLLIB ERROR ')
                                xPrint(tracebackStr)
                                time.sleep(5)
                                continue
                            except urllib2.URLError:
                                tracebackStr= traceback.format_exc()
                                xPrint('URLLIB ERROR ')
                                xPrint(tracebackStr)
                                time.sleep(5)
                                continue
                            except requests.exceptions.RequestException:
                                tracebackStr= traceback.format_exc()
                                xPrint('REQUESTS ERROR ')
                                xPrint(tracebackStr)
                                time.sleep(5)
                                continue
                            except:
                                tracebackStr= traceback.format_exc()
                                xPrint("Unexpected error:")
                                xPrint(tracebackStr)
                                continue
                            xPrint('Retrieved order books.')
                            try:
                                topBidBin = float(binOrderBook['bids'][0][0])
                                topAskBin = float(binOrderBook['asks'][0][0])
                                topBidBit = float(bitOrderBook['buy'][0]['Rate'])
                                topAskBit = float(bitOrderBook['sell'][0]['Rate'])
                            except:
                                topBidBin = bid_bin
                                topAskBin = ask_bin
                                topBidBit = bid_bit
                                topAskBit = ask_bit
                                continue
                            askBitDiff = topAskBit - ask_bit
                            askBinDiff = topAskBin - ask_bin
                            bidBitDiff = topBidBit - bid_bit
                            bidBinDiff = topBidBin - bid_bin
                            quantity, bitPrice, binPrice, pctDiff, grossBitSum, grossBinSum, needMore = determinePriceQuantity(bitOrderBook, binOrderBook, side, base, target, threshold)
                            precision = int(coin_atts[target]['Precision'])
                            quantity = round(0.99999*quantity, precision)
                            bitPrice = '{:.8f}'.format(bitPrice)
                            binPrice = '{:.8f}'.format(binPrice)
                            xPrint('SYMBOL: ', symbol)
                            xPrint('Bittrex: ' + str(bitPrice))
                            xPrint('Binance: ' + str(binPrice))
                            xPrint('Quantity: ' + str(quantity))
                            xPrint('Threshold: ' + str(threshold))
                            xPrint('Base: ', float(bitPrice)*quantity)

                            # If there is not enough capital to even attempt the trade, we should withdraw from the other side to get more. The actual withdraw
                            # functions will take care of checking what coins to withdraw and whether or not there is enough to withdraw from the other side
                            if (needMore == True):
                                xPrint('Getting more of this asset from the other exchange...')
                                if (binPrice > bitPrice): withdrawBuyBittrex(base, target, threshold, bitPrice, binPrice)
                                elif (bitPrice > binPrice): withdrawSellBittrex(base, target, threshold, bitPrice, binPrice)
                                else: xPrint('Prices are equal. No opportunity.')
                                continue

                            # If there is enough capital, we should attempt the trade
                            if ((binPrice > bitPrice) & (float(bitPrice)*quantity > threshold) & (float(binPrice)*quantity > threshold)):
                                xPrint('OPPORTUNITY FOUND')
                                xPrint(symbol + ': ' + str(pctDiff*100) + '%')
                                xPrint('Buy at Bittrex: ' + str(bitPrice))
                                xPrint('Total Base: ' + str(float(bitPrice)*quantity))
                                xPrint('Sell at Binance: ' + str(binPrice))
                                xPrint('Total Base: ' + str(float(binPrice)*quantity))
                                
                                netProfit = 0
                                netBuyCost = 0
                                netSellCost = 0
                                openOrder = True

                                if tradeEnabled == True:
                                    trend = 'down'
                                    # xPrint('Coin is trending down')
                                    xPrint('Difference in ask prices on Bittrex: ', askBitDiff)
                                    xPrint('Difference in bid prices on Binance: ', bidBinDiff)
                                    quantity, netSellCost = sellBinance(symbol, quantity, binPrice, trend)
                                    xPrint('Quantity sold: ', quantity)
                                    quantity = round(1.001*quantity, precision)
                                    if quantity*float(bitPrice) > 0.0011:
                                        uuid, quantity, netBuyCost = buyBittrex(MarketName, quantity, 1.03*float(bitPrice), trend)
                                        xPrint('Quantity bought: ', quantity)

                                netProfit = netSellCost - netBuyCost 
                                xPrint('Cost to buy: ', netBuyCost)
                                xPrint('Gain from sell: ', netSellCost)
                                xPrint('NET PROFIT: ', netProfit, base) 
                                time.sleep(2)         
                                try:
                                    bittrex_balances = bittrex_api.getbalances()
                                    binance_balances = binance_client.get_account()['balances']
                                except KeyboardInterrupt:
                                    tracebackStr= traceback.format_exc()
                                    xPrint('PAUSED')
                                    changeSig = raw_input('Would you like to change the Bittrex/Binance significance (y/n): ')
                                    if changeSig == 'y':
                                        significance = input('Enter new significance: ')
                                    changeSig = raw_input('Would you like to change the Kucoin/Binance significance (y/n): ')
                                    if changeSig == 'y':
                                        significanceKu = input('Enter new significance: ')
                                    resume = raw_input('Hit enter to continue.')
                                    writeBalancesLog(3)
                                    continue
                                except urllib2.HTTPError:
                                    tracebackStr= traceback.format_exc()
                                    xPrint('URLLIB ERROR ')
                                    xPrint(tracebackStr)
                                    time.sleep(5)
                                    continue
                                except urllib2.URLError:
                                    tracebackStr= traceback.format_exc()
                                    xPrint('URLLIB ERROR ')
                                    xPrint(tracebackStr)
                                    time.sleep(5)
                                    continue
                                except requests.exceptions.RequestException:
                                    tracebackStr= traceback.format_exc()
                                    xPrint('REQUESTS ERROR ')
                                    xPrint(tracebackStr)
                                    time.sleep(5)
                                    continue
                                except:
                                    tracebackStr= traceback.format_exc()
                                    xPrint("Unexpected error:")
                                    xPrint(tracebackStr)
                                    resume = raw_input('Hit enter to continue.')
                                    pass
                                baseBitBalance, baseBinBalance, targetBitBalance, targetBinBalance = withdrawBuyBittrex(base, target, threshold, bitPrice, binPrice)
                                writeToLog(symbol, pctDiff, 'Bittrex', float(bitPrice), grossBitSum, 'Binance', float(binPrice), grossBinSum, float(quantity), baseBitBalance, targetBitBalance, baseBinBalance, targetBinBalance, netProfit)
                                time.sleep(2)
                            if ((bitPrice > binPrice) & (float(binPrice)*quantity > threshold) & (float(bitPrice)*quantity > threshold)):
                                xPrint('OPPORTUNITY FOUND')
                                xPrint(symbol + ': ' + str(pctDiff*100) + '%')
                                xPrint('Buy at Binance: ' + str(binPrice))
                                xPrint('Total Base: ' + str(float(binPrice)*quantity))
                                xPrint('Sell at Bittrex: ' + str(bitPrice))
                                xPrint('Total Base: ' + str(float(bitPrice)*quantity))
                                
                                netBuyCost = 0
                                netSellCost = 0
                                netProfit = 0

                                if tradeEnabled == True:
                                    trend = 'up'
                                    # xPrint('Coin is trending up')
                                    xPrint('Difference in ask prices on Binance: ', askBinDiff)
                                    xPrint('Difference in bid prices on Bittrex: ', bidBitDiff)
                                    quantity, netBuyCost = buyBinance(symbol, quantity, binPrice, trend)
                                    quantity = round(0.999*quantity, precision)
                                    xPrint('Quantity bought: ', quantity)
                                    if quantity*float(bitPrice) > 0.0011:
                                        quantity, netSellCost = sellBittrex(MarketName, quantity, 0.97*float(bitPrice), trend) 

                                netProfit = netSellCost - netBuyCost
                                xPrint('Cost to buy: ', netBuyCost)
                                xPrint('Gain from sell: ', netSellCost)
                                xPrint('NET PROFIT: ', netProfit, base)   
                                time.sleep(2)
                                try:       
                                    bittrex_balances = bittrex_api.getbalances()
                                    binance_balances = binance_client.get_account()['balances']
                                except KeyboardInterrupt:
                                    tracebackStr= traceback.format_exc()
                                    xPrint('PAUSED')
                                    changeSig = raw_input('Would you like to change the Bittrex/Binance significance (y/n): ')
                                    if changeSig == 'y':
                                        significance = input('Enter new significance: ')
                                    changeSig = raw_input('Would you like to change the Kucoin/Binance significance (y/n): ')
                                    if changeSig == 'y':
                                        significanceKu = input('Enter new significance: ')
                                    resume = raw_input('Hit enter to continue.')
                                    writeBalancesLog(3)
                                    continue
                                except urllib2.HTTPError:
                                    tracebackStr= traceback.format_exc()
                                    xPrint('URLLIB ERROR ')
                                    xPrint(tracebackStr)
                                    time.sleep(5)
                                    continue
                                except urllib2.URLError:
                                    tracebackStr= traceback.format_exc()
                                    xPrint('URLLIB ERROR ')
                                    xPrint(tracebackStr)
                                    time.sleep(5)
                                    continue
                                except requests.exceptions.RequestException:
                                    tracebackStr= traceback.format_exc()
                                    xPrint('REQUESTS ERROR ')
                                    xPrint(tracebackStr)
                                    time.sleep(5)
                                    continue
                                except:
                                    tracebackStr= traceback.format_exc()
                                    xPrint("Unexpected error:")
                                    xPrint(tracebackStr)
                                    resume = raw_input('Hit enter to continue.')
                                    pass
                                
                                baseBitBalance, baseBinBalance, targetBitBalance, targetBinBalance = withdrawSellBittrex(base, target, threshold, bitPrice, binPrice)
                                
                                writeToLog(symbol, pctDiff, 'Binance', float(binPrice), grossBinSum, 'Bittrex', float(bitPrice), grossBitSum, quantity, baseBitBalance, targetBitBalance, baseBinBalance, targetBinBalance, netProfit)
                                time.sleep(2)

# withdrawBaseX checks each exchange for its current balance of base currencies (BTC or ETH) to see if there is too much/too little on one exchange
#       -A healthy amount of base currencies are constantly needed on each exchange since it's impossible to predict when opportunities will arise on each
#
def withdrawBaseKucoin(base, btcKuBalance, ethKuBalance):
    try:
        withdrew = False
        if (base == 'BTC') & (btcKuBalance > 1.0):
            transferAmount = 0.5
            transferForWithdrawal(asset=base, transferAmount=transferAmount)
            withdrawKucoin = kucoin_client.create_withdrawal(currency=base, amount=transferAmount, address=str(bittrexWallets[base]))
            withdrew = True
        # ETH withdrawals from Kucoin to Bittrex do not work anymore so best we can do is withdraw to Binance.
        elif (base == 'ETH') & (ethKuBalance > 7):
            transferAmount = 3
            transferForWithdrawal(asset=base, transferAmount=transferAmount)
            withdrawKucoin = kucoin_client.create_withdrawal(currency=base, amount=transferAmount, address=str(binanceWallets[base]))
            withdrew = True
        if withdrew: 
            xPrint('Transferring ', base, ' from Kucoin to Bittrex because of an imbalance')
            msg = 'Transferring ' + str(base) + ' from Kucoin to Bittrex because of an imbalance.'
            msgTextSend(msg)
    except:
        tracebackStr= traceback.format_exc()
        xPrint("Unexpected error withdrawing", base, " from Kucoin:")
        xPrint(tracebackStr)
        pass
    return withdrew

def withdrawBaseBittrex(base, btcBitBalance, ethBitBalance):
    withdrew = False
    if (base == 'BTC') & (btcBitBalance > 1.0):
        transferAmount = 0.5
        withdrawBittrex = bittrex_api.withdraw(currency=base, quantity=transferAmount, address=str(kucoinWallets[base]))
        withdrew = True
    elif (base == 'ETH') & (ethBitBalance > 4.5):
        transferAmount = 2
        withdrawBittrex = bittrex_api.withdraw(currency=base, quantity=transferAmount, address=str(kucoinWallets[base]))
        withdrew = True
    if withdrew: xPrint('Transferring ', base, ' from Bittrex to Kucoin because of an imbalance')

    return withdrew

# withdrawBuyX and withdrawSellX ensures that there is enough base/target currencies available on each exchange after each trade for the next opportunity
#       -Called from compKucoinBinance or compBittrexBinance after a trade is initiated to rebalance currencies
#       -This function allows for arbitrage to be so effective since the currencies can be tranferred to other exchanges in a matter of minutes
#
def withdrawBuyBittrex(base, target, threshold, bitPrice, binPrice):
    global bittrex_balances
    global binance_balances
    global coin_atts

    baseBitBalance = 0
    targetBitBalance = 0
    baseBinBalance = 0
    targetBinBalance = 0
    targetBitIndex = 0
    for i in range(0, 10):
        # Will try up to 20 times to withdraw until it succeeds
        try:
            for n in range(0, len(bittrex_balances)):
                if bittrex_balances[n]['Currency'] == base: 
                    available = float(bittrex_balances[n]['Available'])
                    baseBitBalance = available
                    #Since we're buying on Bittrex here, the only asset that could be depleted is base currency
                    if (available < threshold*10) & (base == 'BTC'):
                        baseBinBalance = float(binance_balances[0]['free'])         #BTC is always first in the response list apparently. Probably not good to rely on that though.
                        if baseBinBalance > 1.0:
                            transferAmount = round((baseBinBalance-threshold*20), 3)
                            xPrint('Withdrawing ', transferAmount, ' ', base, ' from Binance')
                            withdrawBinance = binance_client.withdraw(asset=base, address=str(bittrexWallets['BTC']), amount=transferAmount)
                            xPrint(withdrawBinance)
                            coin_atts[base]['numWithdraws'] += 1
                            binance_balances[0]['free'] = baseBinBalance - transferAmount - 0.000002
                    elif (available < threshold*4) & (base == 'ETH'):
                        baseBinBalance = float(binance_balances[2]['free'])         #ETH is always third in the response list apparently. Probably not good to rely on that though.
                        if baseBinBalance > 4:
                            transferAmount = round((baseBinBalance-threshold*5), 3)
                            xPrint('Withdrawing ', transferAmount, ' ', base, ' from Binance')
                            withdrawBinance = binance_client.withdraw(asset=base, address=str(bittrexWallets['ETH']), amount=transferAmount)
                            xPrint(withdrawBinance)
                            coin_atts[base]['numWithdraws'] += 1
                            binance_balances[2]['free'] = baseBinBalance - transferAmount - 0.000002
                if bittrex_balances[n]['Currency'] == target: 
                    targetBitBalance = float(bittrex_balances[n]['Available'])
                    targetBitIndex = n

        except:
            tracebackStr = traceback.format_exc()
            xPrint('Error withdrawing from Binance: ')
            xPrint(tracebackStr)
            # sellBinance(symbol, int(transferAmount), 2*float(binPrice), binance_balances)
            continue
        break
    for n in range(0, len(binance_balances)):
        if binance_balances[n]['asset'] == base: baseBinBalance = float(binance_balances[n]['free'])
        if binance_balances[n]['asset'] == target:
            available = float(binance_balances[n]['free']) 
            targetBinBalance = available
            if (available*float(binPrice) < threshold*1.5) & (target != 'XRP') & (target != 'XLM'):
                transferAmount = round(targetBitBalance*0.8, 3)
                if (transferAmount > float(coin_atts[target]['minWithdraw'])):
                    xPrint('Withdrawing ', transferAmount, ' ', target, ' from Bittrex')
                    withdrawBittrex = bittrex_api.withdraw(currency=target, quantity=transferAmount, address=str(binanceWallets[target]))
                    xPrint(withdrawBittrex)
                    coin_atts[target]['numWithdraws'] += 1
                    bittrex_balances[targetBitIndex]['Available'] = targetBitBalance - transferAmount - 0.000002
                else:
                    xPrint('Not enough of this asset to withdraw.')
                    # coin_atts[target]['goalAlloc'] += allocInc
                    # for n in range(2, len(approved_coins)):
                    #     coin = approved_coins[n]
                    #     if coin != target:
                    #         if coin_atts[coin]['currentAlloc'] > allocFloor: coin_atts[coin]['currentAlloc'] -= allocDec
                    #         else: coin_atts[target]['goalAlloc'] -= allocDec

    return baseBitBalance, baseBinBalance, targetBitBalance, targetBinBalance

def withdrawSellBittrex(base, target, threshold, bitPrice, binPrice):
    global bittrex_balances
    global binance_balances
    global coin_atts

    baseBitBalance = 0
    targetBitBalance = 0
    baseBinBalance = 0
    targetBinBalance = 0
    targetBitIndex = 0
    for n in range(0, len(binance_balances)):
        if binance_balances[n]['asset'] == base: 
            available = float(binance_balances[n]['free'])
            baseBinBalance = available
            if (available < threshold*10) & (base == 'BTC'):
                for i in range(0, len(bittrex_balances)):
                    if bittrex_balances[i]['Currency'] == base: baseBitBalance = float(bittrex_balances[i]['Available'])
                if baseBitBalance > 1.0:
                    transferAmount = round((baseBitBalance-threshold*20), 3)
                    xPrint('Withdrawing ', transferAmount, ' ', base, ' from Bittrex')
                    withdrawBittrex = bittrex_api.withdraw(currency=base, quantity=transferAmount, address=str(binanceWallets['BTC']))
                    xPrint(withdrawBittrex)
                    coin_atts[base]['numWithdraws'] += 1
                    bittrex_balances[i]['Available'] = baseBitBalance - transferAmount - 0.000002
            elif (available < threshold*4) & (base == 'ETH'):
                for i in range(0, len(bittrex_balances)):
                    if bittrex_balances[i]['Currency'] == base: baseBitBalance = float(bittrex_balances[i]['Available'])
                if baseBitBalance > 4:
                    transferAmount = round((baseBitBalance-threshold*4), 3)
                    xPrint('Withdrawing ', transferAmount, ' ', base, ' from Bittrex')
                    withdrawBittrex = bittrex_api.withdraw(currency=base, quantity=transferAmount, address=str(binanceWallets['ETH']))
                    xPrint(withdrawBittrex)
                    coin_atts[base]['numWithdraws'] += 1
                    bittrex_balances[i]['Available'] = baseBitBalance - transferAmount - 0.000002
        if binance_balances[n]['asset'] == target: 
            targetBinBalance = float(binance_balances[n]['free'])
            targetBinIndex = n
    transferAmount = 0
    for e in range(0, 10):
        # Will try up to 10 times to withdraw until it succeeds
        try:
            for n in range(0, len(bittrex_balances)):
                if bittrex_balances[n]['Currency'] == target: 
                    available = float(bittrex_balances[n]['Available'])
                    targetBitBalance = available
                    if (available*float(bitPrice) < threshold*1.5) & (target != 'XRP') & (target != 'XLM'):
                        transferAmount = round(targetBinBalance*0.8, 3)
                        if transferAmount > float(coin_atts[target]['minWithdraw']):
                            xPrint('Withdrawing ', transferAmount, ' ', target, ' from Binance')
                            withdrawBinance = binance_client.withdraw(asset=target, address=str(bittrexWallets[target]), amount=transferAmount)
                            xPrint(withdrawBinance)
                            coin_atts[target]['numWithdraws'] += 1
                            binance_balances[targetBinIndex]['free'] = targetBinBalance - transferAmount - 0.00002
                            
                            # Reallocation calculations
                            # coin_atts[target]['goalAlloc'] += allocInc
                            # for n in range(2, len(approved_coins)):
                            #     coin = approved_coins[n]
                            #     if coin != target:
                            #         if coin_atts[coin]['currentAlloc'] > allocFloor: coin_atts[coin]['currentAlloc'] -= allocDec
                            #         else: coin_atts[target]['goalAlloc'] -= allocDec

                    elif (available*float(bitPrice) < threshold*1.5):
                        transferAmount = round(targetBinBalance*0.8, 3)
                        if transferAmount > float(coin_atts[target]['minWithdraw']):
                            xPrint('Withdrawing ', transferAmount, ' ', target, ' from Binance')
                            withdrawBinance = binance_client.withdraw(asset=target, address=str(bittrexWallets[target]), addressTag=str(extraTags[target]), amount=transferAmount)
                            xPrint(withdrawBinance)
                            coin_atts[target]['numWithdraws'] += 1
                            binance_balances[targetBinIndex]['free'] = targetBinBalance - transferAmount - 0.00002
                        else:
                            xPrint('Not enough of this asset to withdraw.')
                            # Reallocation calculations
                            # coin_atts[target]['goalAlloc'] += allocInc
                            # for n in range(2, len(approved_coins)):
                            #     coin = approved_coins[n]
                            #     if coin != target:
                            #         if coin_atts[coin]['currentAlloc'] > allocFloor: coin_atts[coin]['currentAlloc'] -= allocDec
                            #         else: coin_atts[target]['goalAlloc'] -= allocDec

        # In the event the withdrawal fails due to current Binance bug, this workaround apparently fixes it.
        # Creates an open order that doesn't fill, then cancels it. Somehow this resyncs the available balances.
        except:
            tracebackStr = traceback.format_exc()
            xPrint('Error withdrawing from Binance: ')
            xPrint(tracebackStr)
            # sellBinance(symbol, int(transferAmount), 2*float(binPrice), binance_balances)
            continue
        break

    return baseBitBalance, baseBinBalance, targetBitBalance, targetBinBalance

def withdrawBuyKucoin(base, target, threshold, kuPrice, binPrice):
    global kucoin_balances
    global binance_balances
    global coin_atts

    baseKuBalance = 0
    targetKuBalance = 0
    baseBinBalance = 0
    targetBinBalance = 0
    targetKuIndex = 0
    for i in range(0, 10):
        # Will try up to 10 times to withdraw until it succeeds
        try:
            for n in range(0, len(kucoin_balances)):
                if kucoin_balances[n]['currency'] == base: 
                    available = float(kucoin_balances[n]['balance'])
                    baseKuBalance = available
                    #Since we're buying on Kucoin here, the only asset that could be depleted is base currency
                    if (available < threshold*10) & (base == 'BTC'):
                        baseBinBalance = float(binance_balances[0]['free'])         #BTC is always first in the response list apparently. Probably not good to rely on that though.
                        if baseBinBalance > 1.0:
                            transferAmount = round((baseBinBalance-threshold*15), 3)
                            xPrint('Withdrawing ', transferAmount, ' ', base, ' from Binance')
                            withdrawBinance = binance_client.withdraw(asset=base, address=str(kucoinWallets['BTC']), amount=transferAmount)
                            xPrint(withdrawBinance)
                            coin_atts[base]['numWithdraws'] += 1
                            binance_balances[0]['free'] = baseBinBalance - transferAmount - 0.000002
                    elif (available < threshold*5) & (base == 'ETH'):
                        baseBinBalance = float(binance_balances[2]['free'])         #ETH is always third in the response list apparently. Probably not good to rely on that though.
                        if baseBinBalance > 4:
                            transferAmount = round((baseBinBalance-threshold*5), 3)
                            xPrint('Withdrawing ', transferAmount, ' ', base, ' from Binance')
                            withdrawBinance = binance_client.withdraw(asset=base, address=str(kucoinWallets['ETH']), amount=transferAmount)
                            xPrint(withdrawBinance)
                            coin_atts[base]['numWithdraws'] += 1
                            binance_balances[2]['free'] = baseBinBalance - transferAmount - 0.000002
                # if target == 'NANO': target = 'XRB'
                if kucoin_balances[n]['currency'] == target: 
                    targetKuBalance = float(kucoin_balances[n]['balance'])
                    targetKuIndex = n
                # if target == 'XRB': target = 'NANO'

        except:
            tracebackStr = traceback.format_exc()
            xPrint('Error withdrawing from Binance: ')
            xPrint(tracebackStr)
            # sellBinance(symbol, int(transferAmount), 2*float(binPrice), binance_balances)
            continue
        break
    try:
        for n in range(0, len(binance_balances)):
            if binance_balances[n]['asset'] == base: baseBinBalance = float(binance_balances[n]['free'])
            if binance_balances[n]['asset'] == target:
                available = float(binance_balances[n]['free']) 
                targetBinBalance = available
                if (available*float(binPrice) < threshold*1.5) & (target != 'XRP') & (target != 'XLM'):
                    transferAmount = round(targetKuBalance*0.8, 3)
                    if (transferAmount > float(coin_atts[target]['minWithdraw'])):
                        xPrint('Withdrawing ', transferAmount, ' ', target, ' from Kucoin')
                        # if target == 'NANO': target = 'XRB'
                        transferForWithdrawal(asset=target, transferAmount=transferAmount)
                        withdrawKucoin = kucoin_client.create_withdrawal(currency=target, amount=transferAmount, address=str(binanceWallets[target]))
                        xPrint(withdrawKucoin)
                        # if target == 'XRB': target = 'NANO'
                        coin_atts[target]['numWithdraws'] += 1
                        kucoin_balances[targetKuIndex]['balance'] = targetKuBalance - transferAmount - 0.000002
                        msg = 'Withdrew ' + str(transferAmount) + ' ' + str(target) + ' from Kucoin'
                        msgTextSend(msg)
                    else:
                        xPrint('Not enough of this asset to withdraw.')
                        # coin_atts[target]['goalAlloc'] += allocInc
                        # for n in range(2, len(approved_coins)):
                        #     coin = approved_coins[n]
                        #     if coin != target:
                        #         if coin_atts[coin]['currentAlloc'] > allocFloor: coin_atts[coin]['currentAlloc'] -= allocDec
                        #         else: coin_atts[target]['goalAlloc'] -= allocDec
    except:
        tracebackStr = traceback.format_exc()
        xPrint('Error withdrawing from Kucoin: ')
        xPrint(tracebackStr)
        pass

    return baseKuBalance, baseBinBalance, targetKuBalance, targetBinBalance

def withdrawSellKucoin(base, target, threshold, kuPrice, binPrice):
    global kucoin_balances
    global binance_balances
    global coin_atts

    baseKuBalance = 0
    targetKuBalance = 0
    baseBinBalance = 0
    targetBinBalance = 0
    targetKuIndex = 0
    try:
        for n in range(0, len(binance_balances)):
            if binance_balances[n]['asset'] == base: 
                available = float(binance_balances[n]['free'])
                baseBinBalance = available
                if (available < threshold*10) & (base == 'BTC'):
                    for i in range(0, len(kucoin_balances)):
                        if kucoin_balances[i]['currency'] == base: baseKuBalance = float(kucoin_balances[i]['balance'])
                    if baseKuBalance > 1.0:
                        transferAmount = round((baseKuBalance-threshold*20), 3)
                        transferForWithdrawal(asset=base, transferAmount=transferAmount)
                        xPrint('Withdrawing ', transferAmount, ' ', base, ' from Kucoin')
                        withdrawKucoin = kucoin_client.create_withdrawal(currency=base, amount=transferAmount, address=str(binanceWallets['BTC']))
                        xPrint(withdrawKucoin)
                        coin_atts[base]['numWithdraws'] += 1
                        kucoin_balances[i]['balance'] = baseKuBalance - transferAmount - 0.000002
                        msg = 'Withdrew ' + str(transferAmount) + ' ' + str(base) + ' from Kucoin'
                        msgTextSend(msg)
                elif (available < threshold*3) & (base == 'ETH'):
                    for i in range(0, len(kucoin_balances)):
                        if kucoin_balances[i]['currency'] == base: baseKuBalance = float(kucoin_balances[i]['balance'])
                    if baseKuBalance > 5:
                        transferAmount = round((baseKuBalance-threshold*4), 3)
                        transferForWithdrawal(asset=base, transferAmount=transferAmount)
                        xPrint('Withdrawing ', transferAmount, ' ', base, ' from Kucoin')
                        withdrawKucoin = kucoin_client.create_withdrawal(currency=base, amount=transferAmount, address=str(binanceWallets['ETH']))
                        xPrint(withdrawKucoin)
                        coin_atts[base]['numWithdraws'] += 1
                        kucoin_balances[i]['balance'] = baseKuBalance - transferAmount - 0.000002
                        msg = 'Withdrew ' + str(transferAmount) + ' ' + str(base) + ' from Kucoin'
                        msgTextSend(msg)
            if binance_balances[n]['asset'] == target: 
                targetBinBalance = float(binance_balances[n]['free'])
                targetBinIndex = n
    except:
        tracebackStr = traceback.format_exc()
        xPrint('Error withdrawing from Kucoin: ')
        xPrint(tracebackStr)
        pass
    transferAmount = 0
    for e in range(0, 10):
        # Will try up to 10 times to withdraw until it succeeds
        try:
            for n in range(0, len(kucoin_balances)):
                if kucoin_balances[n]['currency'] == target: 
                    available = float(kucoin_balances[n]['balance'])
                    targetKuBalance = available
                    if (available*float(kuPrice) < threshold*1.5):
                        transferAmount = round(targetBinBalance*0.8, 3)
                        if transferAmount > float(coin_atts[target]['minWithdraw']):
                            xPrint('Withdrawing ', transferAmount, ' ', target, ' from Binance')
                            withdrawBinance = binance_client.withdraw(asset=target, address=str(kucoinWallets[target]), amount=transferAmount)
                            xPrint(withdrawBinance)
                            coin_atts[target]['numWithdraws'] += 1
                            binance_balances[targetBinIndex]['free'] = targetBinBalance - transferAmount - 0.00002
                        else:
                            xPrint('Not enough of this asset to withdraw.')    
                            # Reallocation calculations
                            # coin_atts[target]['goalAlloc'] += allocInc
                            # for n in range(2, len(approved_coins)):
                            #     coin = approved_coins[n]
                            #     if coin != target:
                            #         if coin_atts[coin]['currentAlloc'] > allocFloor: coin_atts[coin]['currentAlloc'] -= allocDec
                            #         else: coin_atts[target]['goalAlloc'] -= allocDec


        # In the event the withdrawal fails due to current Binance bug, this workaround apparently fixes it.
        # Creates an open order that doesn't fill, then cancels it. Somehow this resyncs the available balances.
        except:
            tracebackStr = traceback.format_exc()
            xPrint('Error withdrawing from Binance: ')
            xPrint(tracebackStr)
            # sellBinance(symbol, int(transferAmount), 2*float(binPrice), binance_balances)
            continue
        break

    return baseKuBalance, baseBinBalance, targetKuBalance, targetBinBalance

# compKucoinBinance and compBittrexBinance are the primary functions that perform the bulk of the function calls
#       -Both check the top bid/ask prices for an opportunity as given by the first ticker calls from scanMarkets
#       -If the difference in price between the two exchanges is above the user-specified threshold, orderbooks are retrieved then traversed in determinePriceQuantity
#       -Quantity is not determined or evaluated for significance until determinePriceQuantity since there could be 
#        an opportunity at bid/ask values below the top ones available from the ticker
#       -Currency is transferred back between exchanges via the withdrawBuyX functions after a purchase to ensure they are ready for the next opportunity
#

# buy/sell functions all initiate buy/sell orders and return the transaction id as well as the net cost/profit
#       -This is the most error-prone part of the code as errors can frequently occur because of poor server communication with the exchanges or API calls
#        not returning correct/updated order summary information
#       -Can lead to imbalanced trades and inaccurate profit reporting. Both of which are taken into account as best as possible
#
def buyKucoin(market, quantity, rate, trend):
    xPrint('Buying on Kucoin')
    base = market[-3:]
    target = market[:(len(market)-4)]
    balance = 0   
    netCost = 0
    corrected = False
    begin = time.time()
    for n in range(0, 3):
        try:
            print(market)
            buy_response = kucoin_client.create_limit_order(symbol=market, side='buy', price=rate, size=quantity)
        except:
            # If it's a weird KucoinAPIException where the buy order actually goes through, we want to proceed as normal
            # dealtOrders = kucoin_client.get_dealt_orders(symbol=market, limit=10)['datas']
            # # This will check to make sure the last trade was at least the same coin before assuming the latest order was this buy order that went through
            # if dealtOrders[0]['currency'] == target: 
            #     buy_response = dealtOrders[0]['orderId']
            #     corrected = True
            # else: buy_response = kucoin_client.create_buy_order(symbol=market, price=rate, size=quantity)
            time.sleep(1)
            xPrint('Trying to buy again...')
            continue
        break
    xPrint(buy_response)        #errors out here if the buy fails because buy_response won't exist. Not great error handling but
    timeElapsed = time.time() - begin
    xPrint('Time to make buy call: ', timeElapsed, ' seconds')
    time.sleep(2)       
    if corrected: buy_uuid = buy_response
    else: buy_uuid = str(buy_response['orderId'])
    open_orders = kucoin_client.get_orders(symbol=market, status='active', side='buy')         #delete order if not filled
    xPrint('Open orders: ', open_orders)
    avgPrice = 0
    if len(open_orders) > 0:
        kucoin_client.cancel_all_orders()
        xPrint('Canceled open orders.')
    time.sleep(5)       # Yeah that's right. 5 seconds.
    dealtOrders = kucoin_client.get_orders(symbol=market, status='done')['items']
    quantity = 0
    for n in range(0, len(dealtOrders)):
        if dealtOrders[n]['id'] == buy_uuid: 
            lastOrder = dealtOrders[n]
            netCost += float(lastOrder['dealFunds']) - float(lastOrder['fee'])
            quantity += float(lastOrder['dealSize'])
    if quantity > 0: avgPrice = netCost/quantity
    xPrint('Bought at average price: ', avgPrice)  

    return buy_uuid, quantity, netCost

def sellKucoin(market, quantity, rate, trend):
    xPrint('Selling on Kucoin')
    base = market[-3:]
    target = market[:(len(market)-4)]
    balance = 0   
    netProfit = 0
    corrected = False
    begin = time.time()
    for n in range(0, 3):
        try:
            sell_response = kucoin_client.create_market_order(symbol=market, side='sell', size=quantity)
        except:
            # # If it's a weird KucoinAPIException where the sell order actually goes through, we want to proceed as normal
            # dealtOrders = kucoin_client.get_dealt_orders(symbol=market, limit=10)['datas']
            # # This will check to make sure the last trade was at least the same coin before assuming the latest order was this buy order that went through
            # if dealtOrders[0]['currency'] == target: 
            #     sell_response = dealtOrders[0]['orderId']
            #     corrected = True
            # else: sell_response = kucoin_client.create_sell_order(symbol=market, price=rate, size=quantity)
            time.sleep(1)
            xPrint('Trying to sell again...')
            continue
        break
        
    xPrint(sell_response)
    timeElapsed = time.time() - begin
    xPrint('Time to make sell call: ', timeElapsed, ' seconds')
    time.sleep(2)
    if corrected: sell_uuid = sell_response
    else: sell_uuid = str(sell_response['orderId'])
    open_orders = kucoin_client.get_orders(symbol=market, status='active', side='sell')          #delete order if not filled
    xPrint('Open orders: ', open_orders)
    avgPrice = 0
    if len(open_orders) > 0:                     #At this point, it's been at least 2 sec since the sell call so if the order hasn't filled, it probably isn't going to. Take the slop and live with it.
        kucoin_client.cancel_all_orders()
        xPrint('Canceled open orders.')
    time.sleep(2)           
    dealtOrders = kucoin_client.get_orders(symbol=market, status='done')['items']
    quantity = 0
    avgPrice = 0
    for n in range(0, len(dealtOrders)):
        if dealtOrders[n]['id'] == sell_uuid: 
            lastOrder = dealtOrders[n]
            netProfit += float(lastOrder['dealFunds']) - float(lastOrder['fee'])
            quantity += float(lastOrder['dealSize'])
    if quantity > 0: avgPrice = netProfit/quantity
    xPrint('Sold at average price: ', avgPrice)   

    return quantity, netProfit

def buyBittrex(market, quantity, rate, trend):
    xPrint('Buying on Bittrex')
    base = market[:3]
    target = market[-(len(market)-4):]
    balance = 0   
    # roundingError = 0.999
    # quantity = round(quantity*roundingError, 0)
    begin = time.time()
    buy_response = bittrex_api.buylimit(market=market, quantity=quantity, rate=rate)
    xPrint(buy_response)
    timeElapsed = time.time() - begin
    xPrint('Time to make buy call: ', timeElapsed, ' seconds')
    time.sleep(2)
    # Checking for open orders seems to be the cause of any lopsided trades. Buys on Bittrex do not always immediately show
    # up as an open order even if they don't get filled immediately. Hence the 2 second wait to give it some time to process.
    buy_uuid = str(buy_response['uuid'])
    open_orders = bittrex_api.getopenorders(market=market)          #delete order if not filled
    xPrint('Open orders: ', open_orders)
    avgPrice = 0
    for n in range(0, len(open_orders)):
        bittrex_api.cancel(uuid=open_orders[n]['OrderUuid'])
        xPrint('Canceled open order.')
    time.sleep(5)   # Yep. Waiting 5 seconds to get this order info. Sick of imbalanced trades.
    lastOrder = bittrex_api.getorder(uuid=buy_uuid)
    quantity = float(lastOrder['Quantity']) - float(lastOrder['QuantityRemaining'])
    netCost = abs(float(lastOrder['Price'] + lastOrder['CommissionPaid']))
    if quantity > 0: avgPrice = float(lastOrder['Price'])/quantity
    xPrint('Bought at average price: ', avgPrice)    
    # else:
    #     buy_response = bittrex_api.buymarket(market=market, quantity=quantity) 

    return buy_uuid, quantity, netCost

def sellBittrex(market, quantity, rate, trend):
    xPrint('Selling on Bittrex')
    base = market[:3]
    target = market[-1*(len(market)-4):]
    # Market sells are disabled so we have to settle for limit sells
    # sell_response = bittrex_api.sellmarket(market=market, quantity=quantity)
    # rate = 0.95*float(rate)        # simulates a market sell by offering at a lower price than expected to fill at
    for e in range(0, 5):
        try:
            begin = time.time()
            sell_response = bittrex_api.selllimit(market=market, quantity=quantity, rate=rate)
            xPrint(sell_response)
            timeElapsed = time.time() - begin
            xPrint('Time to make sell call: ', timeElapsed, ' seconds')
        except:
            tracebackStr = traceback.format_exc()
            xPrint('Error selling on Bittrex: ')
            xPrint(tracebackStr)
            continue
        break
            # try:
    uuid = str(sell_response['uuid'])
    time.sleep(2)
    open_orders = bittrex_api.getopenorders(market=market)          #delete order if sommething went wrong
    avgPrice = 0
    for n in range(0, len(open_orders)):
        bittrex_api.cancel(uuid=open_orders[n]['OrderUuid'])
    time.sleep(5)
    lastOrder = bittrex_api.getorder(uuid=uuid)
    quantity = float(lastOrder['Quantity']) - float(lastOrder['QuantityRemaining'])
    netCost = float(lastOrder['Price'] - lastOrder['CommissionPaid'])
    if quantity > 0: avgPrice = float(lastOrder['Price'])/quantity
    xPrint('Sold at average price: ', avgPrice)
    return quantity, netCost

def buyBinance(symbol, quantity, price, trend):
    xPrint('Buying on Binance')
    # if pctDiff < 0.015:
    begin = time.time()
    # if trend == 'up': 
    buy_response = binance_client.order_limit_buy(symbol=symbol, quantity=quantity, price=price)
    # elif trend == 'down': buy_response = binance_client.order_market_buy(symbol=symbol, quantity=quantity)
    xPrint(buy_response)
    timeElapsed = time.time() - begin
    xPrint('Time to make buy call: ', timeElapsed, ' seconds')
    time.sleep(0.5)
    quantity = 0
    netCost = 0
    # for e in range(0, 5):
    #     try:
    buyId = str(buy_response['clientOrderId'])
    orderId = buy_response['orderId']
    # open_orders = binance_client.get_open_orders(symbol=symbol)
    # for n in range(0, len(open_orders)):
    #     clientOrderId = open_orders[n]['clientOrderId']
    #     cancel_response = binance_client.cancel_order(symbol=symbol, origClientOrderId=clientOrderId)
    # time.sleep(0.5)
    orderInfo = binance_client.get_my_trades(symbol=symbol)
    quantity = float(buy_response['executedQty'])
    netCost = 0
    avgPrice = 0
    numOrders = 0
    for i in range(0, len(orderInfo)):
        if orderInfo[i]['orderId'] == orderId:
            # Apparently commission is included in this price
            netCost += float(orderInfo[i]['price'])*float(orderInfo[i]['qty'])
            # netCost += float(orderInfo[i]['price'])*quantity
            # quantity += float(orderInfo[i]['qty'])
            avgPrice += float(orderInfo[i]['price'])
            numOrders += 1
    if numOrders > 0: avgPrice /= numOrders
    xPrint('Bought at average price: ', avgPrice)
        # except:
        #     tracebackStr = traceback.format_exc()
        #     xPrint('Error checking order on Binance: ')
        #     xPrint(tracebackStr)
        #     continue
        # break
        
    # else:
    #     buy_response = binance_client.order_market_buy(symbol=symbol, quantity=quantity)

    return quantity, netCost

def sellBinance(symbol, quantity, price, trend):
    xPrint('Selling on Binance') 
    begin = time.time()
    limitOrderId = 0
    # if trend == 'up':
    #     sell_response = binance_client.order_limit_sell(symbol=symbol, quantity=quantity, price=price)
    #     limitOrderId = sell_response['orderId']
    #     execQty = float(sell_response['executedQty'])
    #     remainingQty = quantity - execQty
    #     xPrint('Sold at limit: ', execQty, '. Remaining quantity: ', remainingQty)
    #     if remainingQty > 0: 
    #         sell_response = binance_client.order_market_sell(symbol=symbol, quantity=remainingQty)
    #         xPrint('Sold at market: ', float(sell_response['executedQty']))
    # elif trend == 'down': 
    sell_response = binance_client.order_limit_sell(symbol=symbol, quantity=quantity, price=price)
    xPrint(sell_response)
    timeElapsed = time.time() - begin
    xPrint('Time to make sell call: ', timeElapsed, ' seconds')
    clientOrderId = str(sell_response['clientOrderId'])
    orderId = sell_response['orderId']
    # if trend == 'up': time.sleep(2)
    # elif trend == 'down': 
    time.sleep(0.5)
    # open_orders = binance_client.get_open_orders(symbol=symbol)
    # xPrint('Open Orders: ', open_orders)
    # for n in range(0, len(open_orders)):
    #     clientOrderId = open_orders[n]['clientOrderId']
    #     cancel_response = binance_client.cancel_order(symbol=symbol, origClientOrderId=clientOrderId)
    orderInfo = binance_client.get_my_trades(symbol=symbol)
    quantity = float(sell_response['executedQty'])
    netCost = 0
    avgPrice = 0
    numOrders = 0
    for i in range(0, len(orderInfo)):
        if (orderInfo[i]['orderId'] == orderId) | (orderInfo[i]['orderId'] == limitOrderId):
            # Apparently commission is included in this price
            # netCost += float(orderInfo[i]['price'])*quantity
            netCost += float(orderInfo[i]['price'])*float(orderInfo[i]['qty'])
            # quantity += float(orderInfo[i]['qty'])
            avgPrice += float(orderInfo[i]['price'])
            numOrders += 1
    if numOrders > 0: avgPrice /= numOrders
    xPrint('Sold at average price: ', avgPrice)
    return quantity, netCost

# regenerateLists initializes the dict objects primarily for logging purposes 
#       -Allows these lists to be automatatically regenerated based on changes to the approved coin pairs between each run
#
def regenerateLists():
    blankRows = json.loads('{"pairRows":[]}')  
    for n in range(0, len(approved_pairs)):
        blankRows['pairRows'].append({'symbol': approved_pairs[n], 'row': 0})

    initialBalances = json.loads('{}')
    for n in range(0, len(approved_coins)):
        if (approved_coins[n] == 'BTC') | (approved_coins[n] == 'ETH'): initialBalances[approved_coins[n]] = {'Bittrex': 0, 'Binance': 0, 'Kucoin': 0}
        else: initialBalances[approved_coins[n]] = {'Bittrex': 0, 'Binance': 0}
    for n in range(0, len(approved_kucoins)):
        if (approved_kucoins[n] != 'BTC') | (approved_kucoins[n] != 'ETH'): initialBalances[approved_kucoins[n]] = {'Kucoin': 0, 'Binance': 0}

    return blankRows, initialBalances

# writeToLog logs every transaction to an Excel book to maintain records for post-processing
#       -Performs as much automated analysis as necessary, such as gross maximum profit in BTC/USD if given unlimited funds, 
#        restricted profit given the actual funds, percentage profit, etc. all taking into account trading fees
#
def writeToLog(pair, pctDiff, buy, ask, sum1, sell, bid, sum2, quantity, baseBitBalance, targetBitBalance, baseBinBalance, targetBinBalance, netProfit):    
    global totalProfit
    
    xPrint('WRITING TO LOG')
    rows = rows_list['pairRows']
    nextRow = 0
    grossMargin = sum2 - sum1
    base = pair[-3:]
    foundPair = False
    if workbook.get_worksheet_by_name(pair) is None:
        worksheet = workbook.add_worksheet(pair)
        # worksheet.write_row(0, 0, ['Timestamp', 'Pct Diff', 'Buy Site', 'Ask Price', 'Total Base', 'Sell Site', 'Bid Price', 'Total Base', 'Bittrex Base Balance', 'Bittrex Target Balance', 'Binance Base Balance', 'Binance Target Balance', 'Gross Margin', 'Net BTC Profit', 'Net USD Profit', 'Pct Gross Margin'])
        worksheet.write_row(0, 0, ['Timestamp', 'Pct Diff', 'Buy Site', 'Ask Price', 'Total Base', 'Sell Site', 'Bid Price', 'Total Base', 'Gross Margin', 'Restricted Margin', 'Net BTC Profit', 'Net USD Profit', 'Pct Gross Margin', 'Pct Restricted Margin'])
    else:
        worksheet = workbook.get_worksheet_by_name(pair)
    
    for p in range(0, len(rows)):
        if rows[p]['symbol'] == pair:
            currentRow = rows[p]['row']
            foundPair = True
            nextRow = currentRow + 1
            rows[p]['row'] = nextRow
            break

    totalBaseBalance = float(baseBitBalance) + float(baseBinBalance)
    totalTargetBalance = float(targetBitBalance) + float(targetBinBalance)
    if base == 'BTC': btcProfit = netProfit 
    else: btcProfit = netProfit*0.1        #eth value
    usdProfit = btcProfit*btcValue
    totalProfit += btcProfit
    pctGrossMargin = round(btcProfit/grossMargin*100, 1)
    if buy == 'Bittrex': restMargin = (quantity*bid*0.999) - (quantity*ask*1.0025)
    elif (buy == 'Binance') & (sell == 'Bittrex'): restMargin = (quantity*bid*0.9975) - (quantity*ask*1.001)
    elif ((buy == 'Binance') & (sell == 'Kucoin')) | (buy == 'Kucoin'): restMargin = (quantity*bid*0.999) - (quantity*ask*1.001)
    if restMargin > 0: pctRestMargin = round(netProfit/restMargin*100, 1)
    else: pctRestMargin = 0
    date_time = datetime.now()         
    date_format = workbook.add_format({'num_format': 'mmm d yyyy hh:mm:ss AM/PM'})

    worksheet.write_datetime(nextRow, 0, date_time, date_format)
    worksheet.write_row(nextRow, 1, [pctDiff*100, buy, ask, sum1, sell, bid, sum2, grossMargin, restMargin, btcProfit, usdProfit, pctGrossMargin, pctRestMargin])
    
    return rows_list, workbook

    # writeBalancesLog is called once at the 

# writeBalancesLog is called when the starting and final balances need to be recorded to show total change in value for every currency.
#       -Called from several error states so that the data isn't lost
#       -Based on xlsxwriter so there are limitations. For instance, an Excel book cannot be reopened and rewritten. It can only be opened and closed once
#       -This is the primary data saved in long-term logs for post-processing. The change in balances is how profits can be accurately tracked each day.
#
def writeBalancesLog(column):
    global traceback
    xPrint('Writing balances to log file.')
    sheetName = ''
    rows = rows_list['pairRows']
    nextRow = 0
    try:
        # Check if this log is being called from the start or at the end of the program
        if column == 0:
            ts = time.time()
            sheetName = datetime.fromtimestamp(ts).strftime('%m-%d')
            worksheet = workbook.add_worksheet(sheetName)
        else:
            worksheet = workbook.get_worksheet_by_name(logSheetName)
        bittrex_balances = bittrex_api.getbalances()
        binance_balances = binance_client.get_account()['balances']
        kucoin_balances = kucoin_client.get_accounts()
        # Since Kucoin is just the worst, the balances are returned in order by their current total BTC value or quantity, which is dynamic and therefore changes between the start and end of a run. The response from this calls therefore needs to be sorted so the calls at the start and end of the logs won't be screwed up.
        newKu_balances = json.loads('[]')
        for n in range(0, len(kucoin_balances)):
            # if kucoin_balances[n]['currency'] == 'XRB': coin = 'NANO'
            coin = kucoin_balances[n]['currency']
            if coin in approved_kucoins:
                if len(newKu_balances) > 0:
                    for i in range(0, len(newKu_balances)):
                        # if newKu_balances[i]['currency'] == 'XRB': currentCoin = 'NANO'
                        currentCoin = newKu_balances[i]['currency']
                        if (currentCoin < coin) & (i != len(newKu_balances)-1): continue      # If coin is later alphabetically, continue to the next coin in  the list
                        elif (currentCoin < coin) & (i == len(newKu_balances)-1): 
                            newKu_balances.append(kucoin_balances[n])
                            break
                        else: 
                            newKu_balances.insert(i, kucoin_balances[n])
                            break
                else: newKu_balances.append(kucoin_balances[n])
        kucoin_balances = newKu_balances
            
        binance_orderbooks = binance_client.get_orderbook_tickers()
        date_time = datetime.now()         
        date_format = workbook.add_format({'num_format': 'mmm d yyyy hh:mm:ss AM/PM'})
        worksheet.write_row(0, column, ['Time:'])
        if column == 0:
            worksheet.write_row(0, 6, ['BTC Value:', btcValue])
            worksheet.write_row(2, column, ['Base', 'Bittrex', 'Binance', 'Kucoin'])
            worksheet.write_row(7, column, ['Symbol', 'Bittrex', 'Binance'])
        else:
            worksheet.write_row(2, column+1, ['Bittrex', 'Binance', 'Kucoin', 'Qty Change', 'BTC Change', 'USD Change', 'Total BTC', 'Total USD', 'Quantity', 'Withdraws'])
            worksheet.write_row(7, column, ['Bittrex', 'Binance', 'Qty Change', 'BTC Change', 'USD Change', 'Total BTC', 'Total USD', 'Quantity', 'Withdraws', 'Missed Opps'])
        worksheet.write_datetime(0, column+1, date_time, date_format)
        row = 8
        totalBtcChange = 0
        totalUsdChange = 0
        for n in range(0, len(bittrex_balances)):
            currentPrice = 0
            if bittrex_balances[n]['Currency'] in approved_coins:
                coin = str(bittrex_balances[n]['Currency'])
                bitBalance = float(bittrex_balances[n]['Available'])
                for i in range(0, len(binance_balances)):
                    if binance_balances[i]['asset'] == coin:
                        binBalance = float(binance_balances[i]['free'])
                if column == 3:
                    for i in range(0, len(binance_orderbooks)):
                        symbol = binance_orderbooks[i]['symbol']
                        binCoin = symbol[:(len(symbol)-3)]
                        if coin == 'BTC': currentPrice = 1
                        elif binCoin == coin:
                            currentPrice = float(binance_orderbooks[i]['askPrice'])
                            # xPrint(binCoin, ' Current Price: ', currentPrice)
                            break
                if column == 0:
                    initialBalances[coin]['Bittrex'] = bitBalance
                    initialBalances[coin]['Binance'] = binBalance
                    xPrint(coin, ' Bittrex Initial Balance: ', bitBalance)
                    xPrint(coin, ' Binance Initial Balance: ', binBalance)
                    if (coin == 'BTC'): worksheet.write_row(3, column, [coin, bitBalance, binBalance])
                    elif (coin == 'ETH'): worksheet.write_row(4, column, [coin, bitBalance, binBalance])
                    else: worksheet.write_row(row, column, [coin, bitBalance, binBalance])
                
                elif (coin == 'BTC'): worksheet.write_row(3, 4, [bitBalance, binBalance])
                elif (coin == 'ETH'): worksheet.write_row(4, 4, [bitBalance, binBalance])
                
                else:
                    initialBitBalance = float(initialBalances[coin]['Bittrex'])
                    initialBinBalance = float(initialBalances[coin]['Binance'])
                    changeInQty = (bitBalance + binBalance) - (initialBitBalance + initialBinBalance)

                    worksheet.write_row(row, column, [bitBalance, binBalance])
                    worksheet.write_row(row, column+8, [coin_atts[coin]['numWithdraws'], coin_atts[coin]['missedOpps']])

                    qtyChangeFormula = '=E' + str(row+1) + ' + D' + str(row+1) + ' - C' + str(row+1) + ' - B' + str(row+1)
                    btcChangeFormula = '=F' + str(row+1) + '*' + str(currentPrice)
                    usdChangeFormula = '=G' + str(row+1) + '*H1'
                    totalBtcFormula = '=(D' + str(row+1) + ' + E' + str(row+1) + ')*' + str(currentPrice)
                    totalUsdFormula = '=I' + str(row+1) + '*H1'
                    totalQtyFormula = '=E' + str(row+1) + ' + D' + str(row+1)
                    worksheet.write_formula(row, column+2, qtyChangeFormula)
                    worksheet.write_formula(row, column+3, btcChangeFormula)
                    worksheet.write_formula(row, column+4, usdChangeFormula)
                    worksheet.write_formula(row, column+5, totalBtcFormula)
                    worksheet.write_formula(row, column+6, totalUsdFormula)
                    worksheet.write_formula(row, column+7, totalQtyFormula)

                if (coin != 'BTC') & (coin != 'ETH'): row += 1

        if column == 0:
            worksheet.write_row(row+2, column, ['Symbol', 'Kucoin', 'Binance'])
        else:
            worksheet.write_row(row+2, column, ['Kucoin', 'Binance', 'Qty Change', 'BTC Change', 'USD Change', 'Total BTC', 'Total USD', 'Quantity', 'Withdraws', 'Missed Opps'])
        
        row += 3
        for n in range(0, len(kucoin_balances)):
            currentPrice = 0
            # if kucoin_balances[n]['currency'] == 'XRB': coin = 'NANO'
            coin = str(kucoin_balances[n]['currency'])
            if coin in approved_kucoins:
                kuBalance = float(kucoin_balances[n]['balance'])
                for i in range(0, len(binance_balances)):
                    if binance_balances[i]['asset'] == coin:
                        binBalance = float(binance_balances[i]['free'])
                if column == 0:
                    initialBalances[coin]['Kucoin'] = kuBalance
                    initialBalances[coin]['Binance'] = binBalance
                    xPrint(coin, ' Kucoin Initial Balance: ', kuBalance)
                    xPrint(coin, ' Binance Initial Balance: ', binBalance)
                    if (coin == 'BTC'): worksheet.write_row(3, column+3, [kuBalance])
                    elif (coin == 'ETH'): worksheet.write_row(4, column+3, [kuBalance])
                    else: worksheet.write_row(row, column, [coin, kuBalance, binBalance])
                    if (coin != 'BTC') & (coin != 'ETH'): row += 1
                else:
                    # Get current price of the coin to convert to BTC value
                    for i in range(0, len(binance_orderbooks)):
                        symbol = binance_orderbooks[i]['symbol']
                        binCoin = symbol[:(len(symbol)-3)]
                        if coin == 'BTC': currentPrice = 1
                        elif binCoin == coin:
                            currentPrice = float(binance_orderbooks[i]['askPrice'])
                            break

                    initialKuBalance = float(initialBalances[coin]['Kucoin'])
                    initialBinBalance = float(initialBalances[coin]['Binance'])
                    changeInQty = (kuBalance + binBalance) - (initialKuBalance + initialBinBalance)
                    
                    rowCopy = row     # Made a copy because 'row' is used for the other coins and shouldn't be permanently changed to 3. Least effort workaround
                    columnCopy = column
                    
                    if (coin == 'BTC'): 
                        row = 3
                        column = 5
                        worksheet.write_row(row, column+1, [kuBalance])
                        qtyChangeFormula = '=SUM(E4:G4) - SUM(B4:D4)'
                        btcChangeFormula = '=H4* ' + str(currentPrice)
                        usdChangeFormula = '=I4*H1'
                        totalBtcFormula = '=SUM(E4:G4)*' + str(currentPrice)
                        totalUsdFormula = '=K4*H1'
                        totalQtyFormula = '=SUM(E4:G4)'
                        worksheet.write_row(row, column+8, [coin_atts[coin]['numWithdraws']])
                    elif (coin == 'ETH'): 
                        row = 4
                        column = 5
                        worksheet.write_row(row, column+1, [kuBalance])
                        qtyChangeFormula = '=SUM(E5:G5) - SUM(B5:D5)'
                        btcChangeFormula = '=H5* ' + str(currentPrice)
                        usdChangeFormula = '=I5*H1'
                        totalBtcFormula = '=SUM(E5:G5)*' + str(currentPrice)
                        totalUsdFormula = '=K5*H1'
                        totalQtyFormula = '=SUM(E5:G5)'
                        worksheet.write_row(row, column+8, [coin_atts[coin]['numWithdraws']])
                    else:
                        worksheet.write_row(row, column, [kuBalance, binBalance])
                        worksheet.write_row(row, column+8, [coin_atts[coin]['numWithdraws'], coin_atts[coin]['missedOpps']])
                        qtyChangeFormula = '=E' + str(row+1) + ' + D' + str(row+1) + ' - C' + str(row+1) + ' - B' + str(row+1)
                        btcChangeFormula = '=F' + str(row+1) + '*' + str(currentPrice)
                        usdChangeFormula = '=G' + str(row+1) + '*H1'
                        totalBtcFormula = '=(D' + str(row+1) + ' + E' + str(row+1) + ')*' + str(currentPrice)
                        totalUsdFormula = '=I' + str(row+1) + '*H1'
                        totalQtyFormula = '=E' + str(row+1) + ' + D' + str(row+1)
                    worksheet.write_formula(row, column+2, qtyChangeFormula)
                    worksheet.write_formula(row, column+3, btcChangeFormula)
                    worksheet.write_formula(row, column+4, usdChangeFormula)
                    worksheet.write_formula(row, column+5, totalBtcFormula)
                    worksheet.write_formula(row, column+6, totalUsdFormula)
                    worksheet.write_formula(row, column+7, totalQtyFormula)
                    
                    row = rowCopy               # Reset 'row' to its original value
                    column = columnCopy
                    if (coin != 'BTC') & (coin != 'ETH'): row += 1
        if column == 3:
            close = raw_input('Write to and close log file? (y/n): ')
            if close == 'y': 
                # Bittrex/Binance totals
                bitRow = 5                                          # bitRow equal to second row for base currency totals (ETH row)
                worksheet.write_row(bitRow, 7, ['Net Total:'])      # write_row is zero-indexed
                sumFormula = '=SUM(I4:I' + str(bitRow) + ')'        # Formulas are not zero-indexed
                sumFormula2 = '=SUM(J4:J' + str(bitRow) + ')'       # Seems unnecessary to make it this instead of SUM(J4:J5) but helps in the future if changes are made
                sumFormula3 = '=SUM(K4:K' + str(bitRow) + ')'
                sumFormula4 = '=SUM(L4:L' + str(bitRow) + ')'
                worksheet.write_formula(bitRow, 8, sumFormula)
                worksheet.write_formula(bitRow, 9, sumFormula2)
                worksheet.write_formula(bitRow, 10, sumFormula3)
                worksheet.write_formula(bitRow, 11, sumFormula4)

                bitRow = len(approved_coins) + 6                    # bitRow now equal to last coin row of Bittrex totals
                worksheet.write_row(bitRow, 5, ['Net Total:'])      # write_row is zero-indexed
                sumFormula = '=SUM(G9:G' + str(bitRow) + ')'        # Formulas are not zero-indexed
                sumFormula2 = '=SUM(H9:H' + str(bitRow) + ')'
                sumFormula3 = '=SUM(I9:I' + str(bitRow) + ')'
                sumFormula4 = '=SUM(J9:J' + str(bitRow) + ')'
                worksheet.write_formula(bitRow, 6, sumFormula)
                worksheet.write_formula(bitRow, 7, sumFormula2)
                worksheet.write_formula(bitRow, 8, sumFormula3)
                worksheet.write_formula(bitRow, 9, sumFormula4)

                # Kucoin/Binance totals
                kuRow = bitRow + len(approved_kucoins) + 1
                kuStart = bitRow + 4
                worksheet.write_row(kuRow, 5, ['Net Total:'])
                sumFormula = '=SUM(G' + str(kuStart) + ':G' + str(kuRow) + ')'
                sumFormula2 = '=SUM(H' + str(kuStart) + ':H' + str(kuRow) + ')'
                sumFormula3 = '=SUM(I' + str(kuStart) + ':I' + str(kuRow) + ')'
                sumFormula4 = '=SUM(J' + str(kuStart) + ':J' + str(kuRow) + ')'
                worksheet.write_formula(kuRow, 6, sumFormula)
                worksheet.write_formula(kuRow, 7, sumFormula2)
                worksheet.write_formula(kuRow, 8, sumFormula3)
                worksheet.write_formula(kuRow, 9, sumFormula4)
                
                # Each pair's totals
                for p in range(0, len(approved_pairs)):
                    pair = approved_pairs[p]
                    if workbook.get_worksheet_by_name(pair) is None:
                        continue 
                    else:
                        worksheet = workbook.get_worksheet_by_name(pair)
                        nextRow = 0
                        for n in range(0, len(rows)):
                            if rows[n]['symbol'] == pair:
                                currentRow = rows[n]['row']
                                foundPair = True
                                nextRow = currentRow + 3            # Should be +1. Temp fix til I can figure out why it's screwing up in the logs
                                rows[n]['row'] = nextRow
                                break
                        avgFormula1 = '=AVERAGE(I2:I' + str(nextRow) + ')'
                        avgFormula2 = '=AVERAGE(J2:J' + str(nextRow) + ')'
                        avgFormula3 = '=AVERAGE(K2:K' + str(nextRow) + ')'
                        avgFormula4 = '=AVERAGE(L2:L' + str(nextRow) + ')'
                        avgFormula5 = '=AVERAGE(M2:M' + str(nextRow) + ')'
                        avgFormula6 = '=AVERAGE(N2:N' + str(nextRow) + ')'
                        sumFormula1 = '=SUM(I2:I' + str(nextRow) + ')'
                        sumFormula2 = '=SUM(J2:J' + str(nextRow) + ')'
                        sumFormula3 = '=SUM(K2:K' + str(nextRow) + ')'
                        sumFormula4 = '=SUM(L2:L' + str(nextRow) + ')'
                        # If there is only one trade for the coin, the STDEV function will give a #DIV/0! error on excel
                        if nextRow > 4:
                            stdFormula1 = '=STDEV(I2:I' + str(nextRow) + ')'
                            stdFormula2 = '=STDEV(J2:J' + str(nextRow) + ')'
                            stdFormula3 = '=STDEV(K2:K' + str(nextRow) + ')'
                            stdFormula4 = '=STDEV(L2:L' + str(nextRow) + ')'
                            stdFormula5 = '=STDEV(M2:M' + str(nextRow) + ')'
                            stdFormula6 = '=STDEV(N2:N' + str(nextRow) + ')'
                        else:
                            stdFormula1 = '=0'
                            stdFormula2 = '=0'
                            stdFormula3 = '=0'
                            stdFormula4 = '=0'
                            stdFormula5 = '=0'
                            stdFormula6 = '=0'
                        worksheet.write_row(nextRow, 7, ['Average:'])
                        worksheet.write_formula(nextRow, 8, avgFormula1)
                        worksheet.write_formula(nextRow, 9, avgFormula2)
                        worksheet.write_formula(nextRow, 10, avgFormula3)
                        worksheet.write_formula(nextRow, 11, avgFormula4)
                        worksheet.write_formula(nextRow, 12, avgFormula5)
                        worksheet.write_formula(nextRow, 13, avgFormula6)
                        worksheet.write_row(nextRow+1, 7, ['Standard Dev:'])
                        worksheet.write_formula(nextRow+1, 8, stdFormula1)
                        worksheet.write_formula(nextRow+1, 9, stdFormula2)
                        worksheet.write_formula(nextRow+1, 10, stdFormula3)
                        worksheet.write_formula(nextRow+1, 11, stdFormula4)
                        worksheet.write_formula(nextRow+1, 12, stdFormula5)
                        worksheet.write_formula(nextRow+1, 13, stdFormula6)
                        worksheet.write_row(nextRow+2, 7, ['Sum:'])
                        worksheet.write_formula(nextRow+2, 8, sumFormula1)
                        worksheet.write_formula(nextRow+2, 9, sumFormula2)
                        worksheet.write_formula(nextRow+2, 10, sumFormula3)
                        worksheet.write_formula(nextRow+2, 11, sumFormula4)
                workbook.close()
                sys.exit()
    except KeyboardInterrupt:
        tracebackStr= traceback.format_exc()
        xPrint('PAUSED')
        changeSig = raw_input('Would you like to change the Bittrex/Binance significance (y/n): ')
        if changeSig == 'y':
            significance = input('Enter new significance: ')
        changeSig = raw_input('Would you like to change the Kucoin/Binance significance (y/n): ')
        if changeSig == 'y':
            significanceKu = input('Enter new significance: ')
        resume = raw_input('Hit enter to continue.')
        writeBalancesLog(3)
        pass
    except:
        tracebackStr= traceback.format_exc()
        xPrint('Error in writeBalancesLog: ')
        xPrint(tracebackStr)
        resume = raw_input('Hit Enter to continue.')
        pass
    
    return sheetName

# printBaseBalances prints the current base currency balances from each exchange to the console and to the text log using xPrint
#       -Useful to see a live status of the balances on each exchange
#       -Does not include an API call. Balances are passed in from main() each iteration
#
def printBaseBalances(bittrex_balances, binance_balances, kucoin_balances):
    try:
        global btcBitBalance
        global btcBinBalance
        global btcKuBalance
        global ethBitBalance
        global ethBinBalance 
        global ethKuBalance
        
        for n in range(0, len(bittrex_balances)):
            if bittrex_balances[n]['Currency'] == 'BTC': btcBitBalance = float(bittrex_balances[n]['Available'])
            if bittrex_balances[n]['Currency'] == 'ETH': ethBitBalance = float(bittrex_balances[n]['Available'])
        xPrint()
        xPrint('Bittrex BTC Balance: ' + str(btcBitBalance))
        xPrint('Bittrex ETH Balance: ' + str(ethBitBalance))

        for n in range(0, len(binance_balances)):
            if binance_balances[n]['asset'] == 'BTC': btcBinBalance = binance_balances[n]['free']
            if binance_balances[n]['asset'] == 'ETH': ethBinBalance = binance_balances[n]['free']
        xPrint()
        xPrint('Binance BTC Balance: ' + str(btcBinBalance))
        xPrint('Binance ETH Balance: ' + str(ethBinBalance))

        for n in range(0, len(kucoin_balances)):
            if kucoin_balances[n]['currency'] == 'BTC': btcKuBalance = kucoin_balances[n]['balance']
            if kucoin_balances[n]['currency'] == 'ETH': ethKuBalance = kucoin_balances[n]['balance']
        xPrint()
        xPrint('Kucoin BTC Balance: ' + str(btcKuBalance))
        xPrint('Kucoin ETH Balance: ' + str(ethKuBalance))
        xPrint() 
    except:
        tracebackStr= traceback.format_exc()
        xPrint('Unexpected Error in printBaseBalances: ')
        xPrint(tracebackStr)
        time.sleep(5)
        pass

    return btcBitBalance, btcBinBalance, btcKuBalance, ethBitBalance, ethBinBalance, ethKuBalance

# msgTextSend initiates an SMTP connection to send a text message from an email account for status updates
#       -Originally used for withdrawal notifications when there was no option for automated Kucoin withdrawals and had to be approved manually
#       -Now used for notifications of withdrawals/periodic status updates
#!#     -Login info removed for distribution purposes
#
def msgTextSend(msg):
    for n in range(1, 6):
        # Will try to send the text message up to 5 times in case of an error
        try:
            username = 'XXXXX@XXXXX.com'
            password = 'XXXXXXX'

            server = smtplib.SMTP('smtp.mail.XXXXX.com', 587)
            server.starttls()
            server.login(username, password)

            fromaddr = 'XXXXX@XXXXXX.com'
            toaddrs  = '1234567890@vtext.com'
            server.sendmail(fromaddr, toaddrs, '\n'+msg)
            server.close()
            xPrint('Text message sent to notify user of withdrawal or status update')
            break
        except:
            tracebackStr = traceback.format_exc()
            xPrint('Unexpected error while sending a text message. Will try ', 5-n, ' more times to send it.')
            xPrint(tracebackStr)
            continue
    return server
                    
# makeInnerTransfer checks for funds deposited in the main account and transfers them to the trading account so they can be used in trades again
#       -Recent addition since Kucoin is the worst and updated their API to include this change
#       -This is different from other exchanges where funds are deposited directly into a trading account. There is no separate main account
#
def makeInnerTransfer():
    tradeId = ''
    mainId = ''
    accounts = kucoin_client.get_accounts()
    for n in range(0, len(accounts)):
        accountType = accounts[n]['type']
        payAccountId = accounts[n]['id']
        coin = accounts[n]['currency']
        available_balance = float(accounts[n]['available'])
        if (accountType == 'main') & (available_balance > 0):
                for i in range(0, len(accounts)):
                    if (accounts[i]['currency'] == coin) & (accounts[i]['type'] == 'trade'):
                        recAccountId = accounts[i]['id']
                inner_transfer_response = str(kucoin_client.create_inner_transfer(from_account_id=payAccountId, to_account_id=recAccountId, amount=available_balance))
                try:
                    xPrint('Inner transfer response: ' + inner_transfer_response)
                    xPrint(available_balance + ' ' + coin + ' transferred from main account to trading account.')
                except:
                    xPrint('Error during inner transfer: ' + inner_transfer_response)

# transferForWithdrawal is similar to makeInnerTransfer but going the opposite direction
#       -Transfers funds from the Kucoin trading account to the main account so that funds can be withdrawn and deposited to another exchange.
#
def transferForWithdrawal(asset, transferAmount):
    tradeId = ''
    mainId = ''
    accounts = kucoin_client.get_accounts()
    for n in range(0, len(accounts)):
        accountType = accounts[n]['type']
        coin = accounts[n]['currency']
        if (accountType == 'main') & (coin == asset):
            recAccountId = accounts[n]['id']
        if (accountType == 'trade') & (coin == asset):
            payAccountId = accounts[n]['id']
    inner_transfer_response = str(kucoin_client.create_inner_transfer(from_account_id=payAccountId, to_account_id=recAccountId, amount=available_balance))
    xPrint('Transferring from Kucoin trading account to Main account for withdrawal...')
    xPrint(inner_transfer_response)

# getOrderBittrex decodes a Bittrex order from the order book.
#       -Would follow a getorderbook API call then convert the retrieved values into a common variable name 
#       -Not used in the code yet but is an example of the abstraction that should be implemented in a future state
#  
def getOrderBittrex(data):  
    ask = float(data['sell'][0]["Rate"])
    askQty = float(data['sell'][0]["Quantity"])
    bid = float(data['buy'][0]["Rate"])
    bidQty = float(data['buy'][0]["Quantity"])
    
    return ask, askQty, bid, bidQty

    ask = float(data['ask'][0]['price'])
    askQty = float(data['ask'][0]['size'])
    bid = float(data['bid'][0]['price'])
    bidQty = float(data['bid'][0]['size'])

    return ask, askQty, bid, bidQty


def closingTime(smtpServer):
    xPrint(coin_atts)
    raw_input("Run completed. Hit enter to finish logging.")
    writeBalancesLog(3)
    done = raw_input("Hit enter to close.")
    smtpServer.close()

###################################################################################################################################################
# Below is the initialization of all global variables and definition of the main function that runs the overall loop of the program.
#       -Definition and initialization of private/public keys
#       -Definition of exchange wallet addresses
#       -Approved pairs of coins and base currencies
#       -Dict objects of coin attributes and statistics
#       -Logbook initialization
#       -User inputs to the console
#

# Initialization of base currency balance variables for each exchange
btcBitBalance = 0
ethBitBalance = 0
btcBinBalance = 0
ethBinBalance = 0
btcKuBalance = 0
ethKuBalance = 0
totalProfit = 0
logEverything = True

# Definition of public wallet addresses. OKAY to distribute since all anyone can do with these is send me payments.
bittrexWallets = json.loads('{"BTC": "175pxvhui5AYvf8tC6CJfQYQBy45Fy1CRq", "ETH": "0xf3e2aa70c596bbeb3cf15f5066c776e8c306bf7d", "ADA":"DdzFFzCqrhsh2kQjDDhPtKhKrfpzrG9KWxeAhcsouTDn3fD3utg8YCUzMQQ5fpbBhUqgPQ3rzayaEdX65Qz9uNyEyfALBfp4wUuoRKTH", "ADX":"0xbf948aabc7a055324a8458600da2dc03aae6e618", "BAT":"0xaef821b14952dc92fb1b7a3b17ad7a06daf96c2b", "LSK":"3949506881155858447L", "STRAT":"SdJzZAbQvnRjFQqugjip7fjowrC46Jr2MZ", "ARK":"AN8imyRRLRXZQ5CN1H7DectFZzUzNWV8ia", "XRP":"rPVMhWBsfF9iMXYj3aAzJVkPDTFNSyWdKy", "XLM":"GB6YPGW5JFMMP2QB2USQ33EUWTXVL4ZT5ITUNCY3YKVWOJPP57CANOF3", "XVG":"D5nPZikmi7mD2hFgtGsjFMBxrDGPWZsDww", "WAVES":"3P9zaUNck2kBii852xE5cAH5upH9UD81Rcw", "KMD":"RJPqh9Yeiveu1F3SxrjTkPCQ3TXFWXnKrs"}')

binanceWallets = json.loads('{"BTC": "1CXd7PtmeofMeLePc4jz46NJTCjFkUzsqt", "ETH": "0xcdb786ffd79d95e18a457ce75f8fe1cd0aa27b3c", "ADA":"DdzFFzCqrhtAFQkvT3oYWG68exfuXACopN2DUvsJYtPUXJuTF2zMEX2N9fVvdZApCGS6UNGeVJJPDhXaDGSPtEwjStaGBUadMLWnBLSo", "ADX":"0xcdb786ffd79d95e18a457ce75f8fe1cd0aa27b3c", "BAT":"0xcdb786ffd79d95e18a457ce75f8fe1cd0aa27b3c", "LSK":"9038926728408369096L", "STRAT":"SiJhcw1mGXpZYHMFXREv2AgtmYVEehF8ug", "ARK":"ALf9ggAocm1gAFDaYvGQdH2Sfc2j4Gju6B", "OMG":"0xcdb786ffd79d95e18a457ce75f8fe1cd0aa27b3c", "XVG":"DB5RUYgaLVJNHL8eojA6bZq1Qj3kKE3Xzd", "WAVES":"3P1wEGzjAL8xnn8tjMvBjFNEYRinXD65fGp", "KMD":"RNFDxkojjMUACVY2biZbKoRBcc86n6gftR", "GAS":"AMCoonjQD1tGknEoCX8BzQBu4p54BDzTi8", "AMB": "0xcdb786ffd79d95e18a457ce75f8fe1cd0aa27b3c", "NEBL":"NgG3yrnckHXvhKoMEomDbeinn4TZSeLR7C", "NANO": "xrb_365xoi3wgg4tkurz4u4wpy8efqnapwn77yh3334uezm8jo1faas9k85g1hj5"}')

kucoinWallets = json.loads('{"BTC": "35UxYo8Kf7SDABSCZg9usoHKMF5RZ5dxEs", "ETH": "0xfd614a818d948898b6d08267790ae785dccb43f8", "NEBL":"NWcATVgV6cSRWpRwnZ5HBBzeY6weWGuPSU", "AMB": "0xfd614a818d948898b6d08267790ae785dccb43f8", "GAS": "AcRFCEtKokiqaCs54EFz8du67rAN6Y7j76", "NANO": "xrb_1117i47ecrxaq94qwd7fcpuk8xxpakqxr9d5gghpbzmbsjfdgit3x1w87ist"}')

extraTags = json.loads('{"XRP": "1662112144", "XLM":"92b5f53b51074801aa5"}')

# Definition of approved coin pairs
approved_pairs = ['NANOBTC', 'GASBTC', 'NEBLBTC', 'AMBBTC', 'ARKBTC', 'STRATBTC', 'LSKBTC', 'ADXBTC', 'ADABTC', 'XRPBTC', 'XLMBTC', 'XVGBTC', 'WAVESBTC', 'KMDBTC', 'ETHBTC', 'ADXETH', 'ADAETH', 'XLMETH', 'XRPETH', 'WAVESETH', 'NEBLETH', 'AMBETH', 'NANOETH']

# Initialization of coin attributes dict object
coin_atts = json.loads('{"BTC": {"Enabled": true, "Precision": 3, "minWithdraw": 0.5, "numWithdraws": 0, "missedOpps": 0, "btcValue": 0, "goalAlloc": 0}, "ETH": {"Enabled": true, "Precision": 3, "minWithdraw": 5, "numWithdraws": 0, "missedOpps": 0, "btcValue": 0, "goalAlloc": 0, "slop": 0}, "ADA": {"Enabled": true, "Precision": 0, "minWithdraw": 50, "numWithdraws": 0, "missedOpps": 0, "btcValue": 0, "goalAlloc": 0, "slop": 0}, "ADX": {"Enabled": false, "Precision": 0, "minWithdraw": 450, "numWithdraws": 0, "missedOpps": 0, "btcValue": 0, "goalAlloc": 0, "slop": 0}, "AMB": {"Enabled": false, "Precision": 0, "minWithdraw": 800, "numWithdraws": 0, "missedOpps": 0, "btcValue": 0, "goalAlloc": 0, "slop": 0}, "ARK": {"Enabled": true, "Precision": 2, "minWithdraw": 50, "numWithdraws": 0, "missedOpps": 0, "btcValue": 0, "goalAlloc": 0, "slop": 0}, "GAS": {"Enabled": true, "Precision": 2, "minWithdraw": 5, "numWithdraws": 0, "missedOpps": 0, "btcValue": 0, "goalAlloc": 0, "slop": 0}, "KMD": {"Enabled": false, "Precision": 2, "minWithdraw": 50, "numWithdraws": 0, "missedOpps": 0, "btcValue": 0, "goalAlloc": 0, "slop": 0}, "LSK": {"Enabled": true, "Precision": 2, "minWithdraw": 50, "numWithdraws": 0, "missedOpps": 0, "btcValue": 0, "goalAlloc": 0, "slop": 0}, "NANO": {"Enabled": true, "Precision": 0, "minWithdraw": 30, "numWithdraws": 0, "missedOpps": 0, "btcValue": 0, "goalAlloc": 0, "slop": 0}, "NEBL": {"Enabled": true, "Precision": 2, "minWithdraw": 50, "numWithdraws": 0, "missedOpps": 0, "btcValue": 0, "goalAlloc": 0, "slop": 0}, "STRAT": {"Enabled": true, "Precision": 2, "minWithdraw": 50, "numWithdraws": 0, "missedOpps": 0, "btcValue": 0, "goalAlloc": 0, "slop": 0}, "WAVES": {"Enabled": false, "Precision": 2, "minWithdraw": 50, "numWithdraws": 0, "missedOpps": 0, "btcValue": 0, "goalAlloc": 0, "slop": 0}, "XLM": {"Enabled": false, "Precision": 0, "minWithdraw": 500, "numWithdraws": 0, "missedOpps": 0, "btcValue": 0, "goalAlloc": 0, "slop": 0}, "XRP": {"Enabled": false, "Precision": 0, "minWithdraw": 100, "numWithdraws": 0, "missedOpps": 0, "btcValue": 0, "goalAlloc": 0, "slop": 0}, "XVG": {"Enabled": true, "Precision": 0, "minWithdraw": 2000, "numWithdraws": 0, "missedOpps": 0, "btcValue": 0, "goalAlloc": 0, "slop": 0}}')

# Definition of individual approved coins for each exchange.
approved_coins = ['BTC', 'ETH', 'ADX', 'LSK', 'STRAT', 'XRP', 'XLM', 'ARK', 'WAVES', 'KMD', 'ADA', 'XVG']

approved_kucoins = ['BTC', 'ETH', 'AMB', 'GAS', 'NANO', 'NEBL']

# Initialization of Kucoin account IDs list
kucoin_accountIds = []

# Logbook and error log definitions and initializations
ts = time.time()
st = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H-%M')
errorLogName = st + ' - Error Log.txt'
errorLog = open(errorLogName, 'w')
workbook_name = st + ' - Trade Opportunities.xlsx'
workbook = xlsxwriter.Workbook(workbook_name)
blankRows, initialBalances = regenerateLists()

# These initializations are in a try block because they rely on error-prone calls
#       -API calls to initialize a verified trading session based on API keys
#       -User input that may not be acceptable for the rest of the program
#
try:

    # Initialization of public/private keys. REMOVED for distribution purposes.
    bittrex_key = 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
    bittrex_secret = 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
    bittrex_api = bittrex(bittrex_key, bittrex_secret)
    bitTradeFee = 0.0025

    binance_key = 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
    binance_secret = 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
    binance_client = Client(binance_key, binance_secret)
    binTradeFee = 0.0010

    kucoin_key = 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
    kucoin_secret = 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
    kucoin_passphrase = 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
    kucoin_client = Client_ku(kucoin_key, kucoin_secret, kucoin_passphrase)
    kuTradeFee = 0.0010

    # User inputs
    profitPct = float(input('Enter minimum percent profit per trade for Bittrex/Binance (in %): '))
    profitPct /= 100
    significance = profitPct + bitTradeFee + binTradeFee
    profitPct = float(input('Enter minimum percent profit per trade for Kucoin/Binance (in %): '))
    profitPct /= 100
    significanceKu = profitPct + kuTradeFee + binTradeFee
    duration = input('Enter number of hours to run: ')
    btcValue = input('Enter current price of BTC for logging purposes: ')
    tradeEnabler = raw_input('Enable trades? (y/n): ')
    if tradeEnabler == 'y':
        tradeEnabled = True
        xPrint('Trades Enabled. Good luck.')
    else: 
        tradeEnabled = False
        xPrint('Trades Disabled.')

    counter = 0
    hoursElapsed = 0
    minsElapsed = 0
    startTime = time.time()
    rows_list = blankRows
    logSheetName = ''
    logSheetName = writeBalancesLog(0)
    totalProfit = 0

except:
    tracebackStr= traceback.format_exc()
    print(tracebackStr)
    xPrint('Error while initializing: ')
    xPrint(tracebackStr)
    resume = raw_input('Hit enter to continue.')
    pass

# main is the Primary loop that calls all of the other functions defined above
#       -Stores user inputs and passes them as parameters to define trading behavior in other functions
#       -Keeps track of the elapsed time to provide timely status updates 
#
def main():
    # Global variables that are modified in this main loop  
    global counter
    global hoursElapsed
    global minsElapsed
    global startTime
    global rows_list
    global logSheetName
    global logSheetName
    global totalProfit
    global smtpServer

    # Very rudimentary elapsed time calculations. Definitely could use polishing but it's functional for now.
    while hoursElapsed < duration:
        try:
            ts = time.time()
            st = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H-%M-%S')
            xPrint(st)
            xPrint()
            xPrint('Retrieving Balances...')
            try:
                bittrex_balances = bittrex_api.getbalances()
                xPrint('Retrieved Bittrex balances.')
                binance_balances = binance_client.get_account()['balances']
                xPrint('Retrieved Binance balances.')
                kucoin_raw_balances = kucoin_client.get_accounts()
                kucoin_balances = []
                for n in range(0, len(kucoin_raw_balances)):
                    if kucoin_raw_balances[n]['type'] == 'trade':           #only add balances from the Kucoin trading accounts, not the Kucoin main accounts
                        kucoin_balances.append(kucoin_raw_balances[n])
                xPrint('Retrieved Kucoin balances.')
            except KeyboardInterrupt:
                tracebackStr= traceback.format_exc()
                xPrint('PAUSED')
                changeSig = raw_input('Would you like to change the Bittrex/Binance significance (y/n): ')
                if changeSig == 'y':
                    significance = input('Enter new significance: ')
                changeSig = raw_input('Would you like to change the Kucoin/Binance significance (y/n): ')
                if changeSig == 'y':
                    significanceKu = input('Enter new significance: ')
                resume = raw_input('Hit enter to continue.')
                writeBalancesLog(3)
                continue
            except:
                tracebackStr= traceback.format_exc()
                xPrint("Unexpected error:")
                xPrint(tracebackStr)
                time.sleep(10)
                continue
            
            if minsElapsed > 59.9:
                xPrint('Current Balances:')
                for n in range(0, len(bittrex_balances)):
                    if bittrex_balances[n]['Currency'] in approved_coins:
                        xPrint(bittrex_balances[n]['Currency'], ' Bittrex Balance: ', float(bittrex_balances[n]['Available']))
                xPrint()
                for n in range(0, len(binance_balances)):
                    if binance_balances[n]['asset'] in approved_coins:
                        xPrint(binance_balances[n]['asset'], ' Binance Balance: ', float(binance_balances[n]['free']))
                xPrint()
                for n in range(0, len(kucoin_balances)):
                    if (kucoin_balances[n]['currency'] in approved_coins):
                        xPrint(kucoin_balances[n]['currency'], ' Kucoin Balance: ', float(kucoin_balances[n]['balance']))
                xPrint()
        
            bittrex_list, binance_list, kucoin_list = scanMarkets(scanBittrex=True, scanBinance=True, scanKucoin=False)
            compBittrexBinance(bittrex_list, binance_list)
            try:
                bittrex_list, binance_list, kucoin_list = scanMarkets(scanBittrex=False, scanBinance=True, scanKucoin=True)
            except:
                tracebackStr= traceback.format_exc()
                xPrint('Error in scanMarkets: ')
                xPrint(tracebackStr)
                time.sleep(5)
                continue
            compKucoinBinance(kucoin_list, binance_list)
            
            btcThreshold = 0.035
            ethThreshold = 0.35
            btcBitBalance, btcBinBalance, btcKuBalance, ethBitBalance, ethBinBalance, ethKuBalance = printBaseBalances(bittrex_balances, binance_balances, kucoin_balances)
            if btcBitBalance < btcThreshold: withdrawBaseKucoin('BTC', btcKuBalance, ethKuBalance)
            elif btcKuBalance < btcThreshold: withdrawBaseBittrex('BTC', btcBitBalance, ethBitBalance)
            if ethBitBalance < ethThreshold: withdrawBaseKucoin('ETH', btcKuBalance, ethKuBalance)
            elif ethKuBalance < ethThreshold: withdrawBaseBittrex('ETH', btcBitBalance, ethBitBalance)

            totalBtcBalance = float(btcBitBalance) + float(btcBinBalance) + float(btcKuBalance)
            totalEthBalance = float(ethBitBalance) + float(ethBinBalance) + float(ethKuBalance)
            
            counter += 1
            currentTime = time.time()
            hoursElapsed = (currentTime - startTime)/3600
            minsElapsed = (hoursElapsed - int(hoursElapsed))*60
            hoursElapsed = int(hoursElapsed)
            remainingHours = duration-hoursElapsed-1
            if remainingHours < 0:
                remainingHours = 0
                minsElapsed = 60
            makeInnerTransfer()
            xPrint('Time Remaining: ', remainingHours, 'hours ', round(60-minsElapsed, 2), ' mins')
            xPrint('Total Gross BTC Profit: ', round(totalProfit, 4))
            xPrint('Total Gross USD Profit: ', round(totalProfit*btcValue, 2))
            xPrint()
            time.sleep(1)

            if (remainingHours % 12 == 0) & (minsElapsed > 59.95): 
                msg = 'Run completed.\n\nTotal BTC: ' + str(totalBtcBalance) + '\nTotal ETH: ' + str(totalEthBalance) + '\n\nEstimated BTC Profit: ' + str(totalProfit)
                smtpServer = msgTextSend(msg)

        except KeyboardInterrupt:
            tracebackStr= traceback.format_exc()
            xPrint('PAUSED')
            changeThresh = raw_input('Would you like to change the Bittrex/Binance significance (y/n): ')
            if changeThresh == 'y':
                threshold = input('Enter new threshold: ')
            changeSig = raw_input('Would you like to change the Kucoin/Binance significance (y/n): ')
            if changeSig == 'y':
                significanceKu = input('Enter new significance: ')
            resume = raw_input('Hit enter to continue.')
            writeBalancesLog(3)
            pass
        except IOError:
            tracebackStr= traceback.format_exc()
            xPrint(tracebackStr)
            xPrint('IO ERROR. RESUMING IN 5 SECONDS...')
            time.sleep(5)
            continue
        except urllib2.HTTPError:
            tracebackStr= traceback.format_exc()
            xPrint('URLLIB ERROR ')
            xPrint(tracebackStr)
            time.sleep(5)
            continue
        except urllib2.URLError:
            tracebackStr= traceback.format_exc()
            xPrint('URLLIB ERROR ')
            xPrint(tracebackStr)
            time.sleep(5)
            continue
        except requests.exceptions.RequestException:
            tracebackStr= traceback.format_exc()
            xPrint('REQUESTS ERROR ')
            xPrint(tracebackStr)
            time.sleep(20)
            continue
        except ValueError:
            tracebackStr= traceback.format_exc()
            xPrint('Value Error ')
            xPrint(tracebackStr)
            time.sleep(5)
            continue
        except:
            tracebackStr= traceback.format_exc()
            xPrint("Unexpected error:")
            xPrint(tracebackStr)
            resume = raw_input('Hit enter to continue.')
            pass
    closingTime(smtpServer)
main()