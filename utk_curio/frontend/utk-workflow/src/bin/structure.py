from bin.consts import fields, fakeScatterData, fakeHmat, fakeScatterSys
import random

class Structure(object):
    def __init__(self) -> None:
        pass

    def getHmat(self, pt, time):
        return fakeHmat
    
    def getScatter(self, fld1, fld2):
        msg = f"[Structure - getScatter] {fld1} {fld2}"

        print(msg)
        # return fakeScatterData
        return fakeScatterSys
    
    def getTemporalData(self, fieldKeys):
        temporalData = {}

        for f in fieldKeys:
            temporalData[f] = []

            for i in range(120):
                v = random.randint(0, 100)

                if i < 96: 
                    t = i + 1 
                    c = "WRFout"
                else:
                    t = i - 95
                    c = "Obs"
                
                obj = {"t": t, "v": v, "c": c, "f": "T" }
                temporalData[f].append(obj)

        return temporalData

    def getFields(self):
        return fields