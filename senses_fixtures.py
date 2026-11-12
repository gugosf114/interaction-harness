"""Small PNG/PDF fixtures made with Python's standard library only."""
from pathlib import Path
import secrets
import struct
import zlib

DIGITS=[
    '01110 10001 10001 10001 10001 10001 01110',
    '00100 01100 00100 00100 00100 00100 01110',
    '01110 10001 00001 00010 00100 01000 11111',
    '11110 00001 00001 01110 00001 00001 11110',
    '00010 00110 01010 10010 11111 00010 00010',
    '11111 10000 10000 11110 00001 00001 11110',
    '01110 10000 10000 11110 10001 10001 01110',
    '11111 00001 00010 00100 01000 01000 01000',
    '01110 10001 10001 01110 10001 10001 01110',
    '01110 10001 10001 01111 00001 00001 01110',
]


def png(path,number):
    scale=10;width=6*7*scale+2*scale;height=11*scale
    pixels=bytearray([255])*(width*height*3)
    for index,digit in enumerate(number):
        pattern=DIGITS[int(digit)].replace(' ','')
        for y in range(7):
            for x in range(5):
                if pattern[y*5+x]=='1':
                    for yy in range((y+2)*scale,(y+3)*scale):
                        start=(yy*width+(index*7+x+2)*scale)*3
                        pixels[start:start+scale*3]=b'\0'*(scale*3)
    raw=b''.join(b'\0'+pixels[y*width*3:(y+1)*width*3] for y in range(height))
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))


def pdf(path,sentence):
    safe=sentence.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
    stream=('BT /F1 18 Tf 40 700 Td ('+safe+') Tj ET\n').encode('ascii')
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 792 612] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'endstream']
    # Landscape page, with the baseline inside the visible page.
    objects[4]=objects[4].replace(b'40 700 Td',b'40 500 Td')
    data=bytearray(b'%PDF-1.4\n');offsets=[]
    for i,obj in enumerate(objects,1):offsets.append(len(data));data+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    start=len(data);data+=f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode()
    for pos in offsets:data+=f'{pos:010d} 00000 n \n'.encode()
    data+=f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()
    Path(path).write_bytes(data)


def create(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    number=f'{secrets.randbelow(1_000_000):06d}'
    sentence='Quiet amber otters carry '+secrets.choice(['seven','nine','eleven'])+' copper keys '+secrets.token_hex(3)+'.'
    image=folder/'number.png';document=folder/'sentence.pdf';png(image,number);pdf(document,sentence)
    return {'number':number,'sentence':sentence,'image':str(image),'file':str(document)}
