"""复用已验收的固定27交易日缺口请求器，输出到独立研究目录。"""
import prepare_entry_gap
from recovery_research import OUT

if __name__=='__main__':
    prepare_entry_gap.OUT=OUT
    prepare_entry_gap.main()
