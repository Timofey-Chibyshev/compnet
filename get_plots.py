import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

plt.style.use('default')
plt.rcParams['font.size'] = 12

df_window = pd.read_csv('window_size_results_loss_0.3_good_mod.csv')
df_loss = pd.read_csv('loss_probability_results_window_3_good.csv')

df_window = df_window[df_window['delivered'] > 0]
df_loss = df_loss[df_loss['delivered'] > 0]

fig1, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
fig1.canvas.manager.set_window_title('Зависимости от вероятности потерь')

for protocol in ['GBN', 'SR']:
    data = df_loss[df_loss['protocol'] == protocol]
    ax1.plot(data['loss'], data['efficiency'], marker='o', label=protocol, linewidth=2)
ax1.set_xlabel('Вероятность потерь')
ax1.set_ylabel('Коэффициент эффективности')
ax1.set_title('Зависимость эффективности от вероятности потерь')
ax1.legend()
ax1.grid(True, linestyle='--', alpha=0.7)

for protocol in ['GBN', 'SR']:
    data = df_loss[df_loss['protocol'] == protocol]
    ax2.plot(data['loss'], data['time'], marker='s', label=protocol, linewidth=2)
ax2.set_xlabel('Вероятность потерь')
ax2.set_ylabel('Время передачи (мс)')
ax2.set_title('Зависимость времени передачи от вероятности потерь')
ax2.legend()
ax2.grid(True, linestyle='--', alpha=0.7)

plt.tight_layout()
plt.show(block=False)

fig2, (ax3, ax4) = plt.subplots(1, 2, figsize=(15, 6))
fig2.canvas.manager.set_window_title('Зависимости от размера окна')

for protocol in ['GBN', 'SR']:
    data = df_window[df_window['protocol'] == protocol]
    ax3.plot(data['W'], data['efficiency'], marker='^', label=protocol, linewidth=2)
ax3.set_xlabel('Размер окна')
ax3.set_ylabel('Коэффициент эффективности')
ax3.set_title('Зависимость эффективности от размера окна')
ax3.legend()
ax3.grid(True, linestyle='--', alpha=0.7)

for protocol in ['GBN', 'SR']:
    data = df_window[df_window['protocol'] == protocol]
    ax4.plot(data['W'], data['time'], marker='d', label=protocol, linewidth=2)
ax4.set_xlabel('Размер окна')
ax4.set_ylabel('Время передачи (мс)')
ax4.set_title('Зависимость времени передачи от размера окна\n(логарифмическая шкала)')
ax4.set_yscale('log')  # Логарифмическая шкала по оси Y
ax4.legend()
ax4.grid(True, linestyle='--', alpha=0.7)

ax4.grid(True, which='minor', linestyle=':', alpha=0.4)

plt.tight_layout()
plt.show(block=False)

fig3, ax5 = plt.subplots(1, 1, figsize=(10, 6))
fig3.canvas.manager.set_window_title('Разность эффективности протоколов')

gbn_data = df_loss[df_loss['protocol'] == 'GBN'].sort_values('loss')
sr_data = df_loss[df_loss['protocol'] == 'SR'].sort_values('loss')

efficiency_diff = sr_data['efficiency'].values - gbn_data['efficiency'].values

ax5.plot(gbn_data['loss'], efficiency_diff, marker='o', color='red', linewidth=2)
ax5.set_xlabel('Вероятность потерь')
ax5.set_ylabel('Разность эффективности (SR - GBN)')
ax5.set_title('Разность эффективности протоколов от вероятности потерь')
ax5.grid(True, linestyle='--', alpha=0.7)

plt.tight_layout()
plt.show(block=False)

fig1.savefig('loss_dependencies.png', dpi=300, bbox_inches='tight')
fig2.savefig('window_dependencies.png', dpi=300, bbox_inches='tight')
fig3.savefig('efficiency_difference.png', dpi=300, bbox_inches='tight')

print("Все графики отображены в отдельных окнах.")
print("Закройте все окна для завершения программы.")
plt.show()
