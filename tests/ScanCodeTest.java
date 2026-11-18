package io.github.nearbyconnect;

import java.awt.image.BufferedImage;
import javax.imageio.ImageIO;
import java.io.File;
import com.google.zxing.*;
import com.google.zxing.common.HybridBinarizer;
import com.google.zxing.qrcode.QRCodeReader;

class ScanCodeTest {
    public static void main(String[] args) throws Exception {
        BufferedImage image = ImageIO.read(new File(args[0]));
        int width = image.getWidth(), height = image.getHeight();
        byte[] frame = new byte[width * height];
        for (int y = 0; y < height; y++)
            for (int x = 0; x < width; x++)
                frame[y * width + x] = (byte) image.getRGB(x, y);
        PlanarYUVLuminanceSource source = new PlanarYUVLuminanceSource(frame, width, height,
            0, 0, width, height, false);
        String link = new QRCodeReader().decode(new BinaryBitmap(new HybridBinarizer(source))).getText();
        assert Binding.parse(link) != null;
    }
}
