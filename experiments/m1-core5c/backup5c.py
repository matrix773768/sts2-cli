"""Combine witnessed continuations at common public decisions, retaining original leaf probabilities."""
from collections import defaultdict
def combine(policies,score,depth=0):
    def best(options):
        return max(options,key=lambda rows:score(rows)[1])
    if len(policies)==1:
        return policies[0]
    actions=defaultdict(list)
    for rows in policies:
        action=rows[0][3][depth]
        if any(row[3][depth]!=action for row in rows):
            raise ValueError("non-public choice")
        actions[action].append(rows)
    solutions=[]
    for variants in actions.values():
        if len(variants)==1:
            solutions.append(variants[0])
            continue
        parts=[]
        for rows in variants:
            bins=defaultdict(list)
            for row in rows:
                path=row[3]
                key=path[depth+1][0] if len(path)>depth+1 else None
                bins[key].append(row)
            parts.append(bins)
        original=parts[0]
        masses={k:sum(r[0] for r in group) for k,group in original.items()}
        if any(p.keys()!=original.keys() or any(abs(sum(r[0] for r in p[k])-m)>1e-10 for k,m in masses.items()) for p in parts[1:]):
            # A different representation of an observation cannot authorize switching programs.
            solutions.append(best(variants))
            continue
        solved=[]
        for key in original:
            variants_at_obs=[p[key] for p in parts]
            solved.extend(original[key] if key is None else combine(variants_at_obs,score,depth+1))
        solutions.append(solved)
    return best(solutions)
