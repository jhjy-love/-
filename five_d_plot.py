import numpy as np
import matplotlib.pyplot as plt
from matplotlib import cm


def plot_5d(x, y, z, c, s, filename="5d_plot.png"):
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')
    scatter = ax.scatter(x, y, z, c=c, s=s, cmap=cm.viridis, alpha=0.8)
    fig.colorbar(scatter, ax=ax, label='Dimension 4')
    ax.set_xlabel('X')
    ax.set_ylabel('Y')
    ax.set_zlabel('Z')
    plt.savefig(filename)
    plt.close(fig)


if __name__ == "__main__":
    np.random.seed(0)
    n = 100
    x, y, z = np.random.rand(3, n)
    c = np.random.rand(n)
    s = (np.random.rand(n) * 100) + 20
    plot_5d(x, y, z, c, s)
    print("Plot saved to 5d_plot.png")
