const canvas =
document.getElementById(
    "neural-network"
);

const ctx =
canvas.getContext("2d");

let width;
let height;

let nodes = [];

let mouse = {
    x: null,
    y: null
};


/* ---------------------------------------------------------
 R ESI*ZE
 --------------------------------------------------------- */

function resize() {

    width =
    canvas.width =
    window.innerWidth;

    height =
    canvas.height =
    window.innerHeight;

    createNodes();
}


/* ---------------------------------------------------------
 C REA*TE NODES
 --------------------------------------------------------- */

function createNodes() {

    nodes = [];

    const amount =
    Math.min(
        100,
        Math.max(
            40,
            Math.floor(
                width * height / 16000
            )
        )
    );

    for (
        let i = 0;
    i < amount;
    i++
    ) {

        nodes.push({

            x:
            Math.random()
            * width,

            y:
            Math.random()
            * height,

            vx:
            (Math.random() - .5)
            * .22,

            vy:
            (Math.random() - .5)
            * .22,

            r:
            Math.random()
            * 1.6
            + .7

        });

    }

}


/* ---------------------------------------------------------
 D RAW*
 --------------------------------------------------------- */

function draw() {

    ctx.clearRect(
        0,
        0,
        width,
        height
    );


    /* Move nodes */

    for (const node of nodes) {

        node.x += node.vx;
        node.y += node.vy;


        if (
            node.x < 0 ||
            node.x > width
        ) {

            node.vx *= -1;

        }


        if (
            node.y < 0 ||
            node.y > height
        ) {

            node.vy *= -1;

        }


        /* Mouse influence */

        if (
            mouse.x !== null
        ) {

            const dx =
            mouse.x -
            node.x;

            const dy =
            mouse.y -
            node.y;

            const distance =
            Math.sqrt(
                dx * dx +
                dy * dy
            );

            if (
                distance < 180 &&
                distance > 1
            ) {

                const force =
                (180 - distance)
                / 180;

                node.x -=
                dx / distance
                * force
                * .18;

                node.y -=
                dy / distance
                * force
                * .18;

            }

        }

    }


    /* Connections */

    for (
        let i = 0;
    i < nodes.length;
    i++
    ) {

        for (
            let j = i + 1;
        j < nodes.length;
        j++
        ) {

            const a =
            nodes[i];

            const b =
            nodes[j];

            const dx =
            a.x - b.x;

            const dy =
            a.y - b.y;

            const distance =
            Math.sqrt(
                dx * dx +
                dy * dy
            );

            if (
                distance < 145
            ) {

                const opacity =
                (1 - distance / 145)
                * .20;

                ctx.beginPath();

                ctx.strokeStyle =
                `rgba(
                    0,
                    234,
                    255,
                    ${opacity}
                )`;

                ctx.lineWidth =
                .5;

                ctx.moveTo(
                    a.x,
                    a.y
                );

                ctx.lineTo(
                    b.x,
                    b.y
                );

                ctx.stroke();

            }

        }

    }


    /* Nodes */

    for (
        const node of nodes
    ) {

        ctx.beginPath();

        ctx.fillStyle =
        "rgba(0,234,255,.65)";

ctx.shadowColor =
"rgba(0,234,255,.9)";

ctx.shadowBlur =
8;

ctx.arc(
    node.x,
    node.y,
    node.r,
    0,
    Math.PI * 2
);

ctx.fill();

ctx.shadowBlur =
0;

    }


    requestAnimationFrame(
        draw
    );

}


/* ---------------------------------------------------------
 M OUS*E
 --------------------------------------------------------- */

window.addEventListener(
    "mousemove",
    event => {

        mouse.x =
        event.clientX;

        mouse.y =
        event.clientY;

    }
);


window.addEventListener(
    "mouseleave",
    () => {

        mouse.x =
        null;

        mouse.y =
        null;

    }
);


/* ---------------------------------------------------------
 S TAR*T
 --------------------------------------------------------- */

window.addEventListener(
    "resize",
    resize
);

resize();

draw();
